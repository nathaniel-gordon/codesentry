"""The autonomous review agent: tools over a ReviewSession plus two planners.

The agent is not a wrapper around a single `analyze()` call. It discovers the
file list, decides what to analyze next, then follows up on what it learned - the
secret-scan step exists because a text search can reach `.ini`/`.env` files that
no AST pass can see, and the agent has to notice the hits and record them itself.
That investigation is what the trace shows.

Two planners are available and both drive the identical tool surface:
  * `deterministic_policy` - default, offline, reproducible;
  * an LLM planner (`llm_policy_factory`) when ANTHROPIC_API_KEY is set and
    `--planner llm` is requested. `get_llm()` returning None silently selects the
    deterministic planner, so the CLI behaves identically offline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .agent_core import Agent, Step, Tool, ToolRegistry, llm_policy_factory
from .analyzers import SEVERITY_ORDER
from .errors import ToolInputError
from .review import SECRET_SCAN_RE, ReviewSession
from .textscan import search_text_files

SYSTEM_PROMPT = (
    "You are a senior Python code reviewer. Investigate the repository with the "
    "tools until every file has been analyzed, clones have been scanned, "
    "complexity has been inspected and configuration files have been searched "
    "for credentials. Record any credential you find with record_finding.")


@dataclass
class AgentTools:
    """Tool implementations bound to one ReviewSession."""

    session: ReviewSession
    max_hits: int = 40

    # -- individual tools --------------------------------------------------
    def list_files(self) -> str:
        """Enumerate the Python files in scope."""
        files = self.session.files
        head = "\n".join(files[:60])
        extra = f"\n... {len(files) - 60} more" if len(files) > 60 else ""
        return f"{len(files)} python files:\n{head}{extra}"

    def analyze_file(self, path: str) -> str:
        """Run the four analyzer passes over one file."""
        if path not in self.session.files:
            raise ToolInputError("path is not in review scope", path=str(path)[:200])
        produced = self.session.analyze_file(path)
        counts: dict[str, int] = {}
        for finding in produced:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        metrics = self.session.metrics[path]
        detail = ", ".join(f"{sev}={counts[sev]}" for sev in SEVERITY_ORDER
                           if counts.get(sev))
        return (f"{path}: {len(produced)} findings"
                f"{' (' + detail + ')' if detail else ''}; "
                f"sloc={metrics.sloc} funcs={len(metrics.functions)} "
                f"max_cc={metrics.max_complexity} coupling={metrics.coupling}")

    def complexity_report(self, top: int = 5) -> str:
        """Rank the analyzed functions by cyclomatic complexity."""
        try:
            limit = min(200, max(1, int(top)))
        except (TypeError, ValueError) as exc:
            raise ToolInputError("top must be an integer", top=repr(top)) from exc
        fns = [fn for m in self.session.metrics.values() for fn in m.functions]
        if not fns:
            return "no functions analyzed yet"
        fns.sort(key=lambda f: (-f.complexity, f.file, f.line))
        rows = [f"{f.file}:{f.line} {f.name} cc={f.complexity} "
                f"nesting={f.nesting} len={f.length} params={f.params}"
                for f in fns[:limit]]
        worst_module = max(self.session.metrics.values(),
                           key=lambda m: (m.coupling, m.file))
        return ("worst functions:\n" + "\n".join(rows)
                + f"\nhighest coupling: {worst_module.file} "
                  f"({worst_module.coupling} modules)")

    def duplicate_scan(self) -> str:
        """Find structurally duplicated functions across every analyzed file."""
        added = self.session.scan_duplicates()
        pairs = self.session.duplicate_pairs
        if not pairs:
            return "no duplicate blocks above the similarity threshold"
        listed = "; ".join(f"{p.a.file}:{p.a.line}~{p.b.file}:{p.b.line} "
                           f"({p.similarity:.0%})" for p in pairs[:5])
        return f"{len(pairs)} duplicate pair(s), {added} finding(s) recorded: {listed}"

    def search_pattern(self, pattern: str) -> str:
        """Regex-search the repository's text files, which no AST pass can read.

        The pattern is validated and the scan is bounded (see `textscan`);
        `ToolInputError` propagates so the loop records it as a real error
        rather than a plain observation.
        """
        hits = search_text_files(self.session.root, pattern, max_hits=self.max_hits)
        if not hits:
            return "0 matches"
        listed = "\n".join(f"{h.file}:{h.line}:{h.text}" for h in hits)
        return f"{len(hits)} matches:\n{listed}"

    def record_finding(self, file: str, line: int, rule: str, message: str,
                       suggestion: str, severity: str = "", category: str = "",
                       why: str = "") -> str:
        """Store a finding the agent derived outside the AST passes."""
        added = self.session.record(file, line, rule, message, suggestion,
                                    severity, category, why)
        return (f"recorded {rule} at {file}:{line}" if added
                else f"duplicate finding ignored at {file}:{line}")

    def registry(self) -> ToolRegistry:
        """Build the registry the Agent loop calls into."""
        reg = ToolRegistry()
        reg.register(Tool("list_files", "list every Python file in review scope",
                          self.list_files, {}))
        reg.register(Tool("analyze_file",
                          "run security/correctness/complexity/maintainability passes "
                          "over one file", self.analyze_file,
                          {"path": "repo-relative path"}))
        reg.register(Tool("complexity_report",
                          "rank analyzed functions by cyclomatic complexity",
                          self.complexity_report, {"top": "how many rows"}))
        reg.register(Tool("duplicate_scan",
                          "detect copy-pasted functions across analyzed files",
                          self.duplicate_scan, {}))
        reg.register(Tool("search_pattern",
                          "regex search over the repo's config/text files",
                          self.search_pattern, {"pattern": "regex"}))
        reg.register(Tool("record_finding", "store a finding the agent derived itself",
                          self.record_finding,
                          {"file": "path", "line": "line number", "rule": "rule id",
                           "message": "what is wrong", "suggestion": "how to fix",
                           "severity": "critical|high|medium|low",
                           "category": "security|correctness|complexity|maintainability",
                           "why": "why it matters"}))
        return reg


HIT_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<text>.*)$")


def deterministic_policy(session: ReviewSession):
    """Rule-based planner: discover, analyze, cross-check, follow up, finish.

    The follow-up stage parses the agent's own search observation, so the
    credentials it records are ones it actually found during the run rather than
    a pre-computed list handed to it.
    """

    def policy(goal: str, history: list[Step], registry: ToolRegistry) -> dict:
        done = [s.action for s in history]
        if "list_files" not in done:
            return {"thought": "Start by establishing the review scope.",
                    "action": "list_files", "action_input": {}}
        analyzed = {s.action_input.get("path") for s in history
                    if s.action == "analyze_file"}
        pending = [f for f in session.files if f not in analyzed]
        if pending:
            nxt = pending[0]
            return {"thought": f"{len(pending)} file(s) still unreviewed; take "
                              f"'{nxt}' next.",
                    "action": "analyze_file", "action_input": {"path": nxt}}
        if "duplicate_scan" not in done:
            return {"thought": "Every file is parsed, so clone detection can now "
                              "compare all of them at once.",
                    "action": "duplicate_scan", "action_input": {}}
        if "complexity_report" not in done:
            return {"thought": "Inspect the complexity hot spots that drive risk "
                              "ranking.",
                    "action": "complexity_report", "action_input": {"top": 5}}
        if "search_pattern" not in done:
            return {"thought": "AST passes only see Python; search config files for "
                              "credentials they cannot reach.",
                    "action": "search_pattern",
                    "action_input": {"pattern": SECRET_SCAN_RE}}
        recorded = {(s.action_input.get("file"), int(s.action_input.get("line", 0)))
                    for s in history if s.action == "record_finding"}
        for step in history:
            if step.action != "search_pattern":
                continue
            for raw in step.observation.splitlines()[1:]:
                hit = HIT_RE.match(raw)
                if not hit:
                    continue
                file, line = hit.group("file"), int(hit.group("line"))
                if (file, line) in recorded:
                    continue
                key = hit.group("text").split("=")[0].strip() or "credential"
                return {
                    "thought": f"'{file}:{line}' assigns a credential in a config "
                               "file that ships with the repo.",
                    "action": "record_finding",
                    "action_input": {
                        "file": file, "line": line, "rule": "hardcoded-secret",
                        "message": f"configuration key '{key}' holds a literal "
                                   "credential",
                        "suggestion": "move the value to a secret manager, "
                                      "reference it by name, and rotate it",
                    }}
        return {"thought": f"Scope covered: {len(session.findings)} findings across "
                          f"{len(session.metrics)} files.",
                "action": "finish",
                "action_input": {"answer": f"reviewed {len(session.metrics)} files, "
                                           f"{len(session.findings)} findings"}}

    return policy


def build_agent(session: ReviewSession, planner: str = "auto",
                max_steps: int = 0) -> tuple[Agent, str]:
    """Construct the review agent; returns (agent, planner name actually used).

    'auto'/'rules' use the deterministic planner. 'llm' upgrades to a Claude
    planner only when credentials exist - otherwise it degrades silently, which
    is what keeps the demo reproducible offline.
    """
    tools = AgentTools(session)
    registry = tools.registry()
    steps = max_steps or (len(session.files) + 12)
    used = "deterministic"
    policy = deterministic_policy(session)
    if planner == "llm":
        from .llm import get_llm
        llm = get_llm()
        if llm is not None:
            policy = llm_policy_factory(llm, SYSTEM_PROMPT)
            used = "claude"
    return Agent("code-review-agent", registry, policy, max_steps=steps), used
