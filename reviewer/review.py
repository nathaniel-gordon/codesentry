"""Review session: the mutable store the agent's tools write into, plus scoring.

The agent does not compute results; it *drives* this session. Every tool call
lands here, so a review assembled by the deterministic planner and one assembled
by an LLM planner produce the same shaped result, and the risk model has a single
implementation.
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field as dc_field

from .analyzers import (CATEGORIES, SEVERITY_ORDER, SEVERITY_WEIGHT, AnalyzerConfig,
                        Finding, RuleSpec, RULES, analyze_source)
from .cache import AnalysisCache
from .churn import ChurnModel, build_churn
from .diffing import DiffStat, filter_findings, iter_python_files
from .duplication import CodeBlock, duplicate_findings, extract_blocks, find_duplicates
from .errors import AnalysisError, InputError, ToolInputError
from .logging_setup import get_logger
from .metrics import ModuleMetrics, module_metrics
from .suppression import Suppressions
from .textscan import search_text_files

GRADES = ((90.0, "A"), (80.0, "B"), (70.0, "C"), (60.0, "D"), (0.0, "F"))
SECRET_SCAN_RE = (r"(?i)\w*(?:secret|api[_-]?key|password|passwd|token)\w*"
                  r"\s*[:=]\s*[\"']?[A-Za-z0-9+/_\-]{12,}")

log = get_logger("review")


@dataclass
class HealthScore:
    """Repo health on 0-100 with the penalty breakdown that produced it."""

    score: float
    grade: str
    components: dict[str, float]

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {"score": round(self.score, 1), "grade": self.grade,
                "components": {k: round(v, 2) for k, v in self.components.items()}}


@dataclass
class ReviewResult:
    """Everything one review produced, ready for the report writers."""

    root: str
    findings: list[Finding]
    metrics: dict[str, ModuleMetrics]
    health: HealthScore
    churn: ChurnModel
    duplicate_pairs: list
    trace: str = ""
    diff_stat: DiffStat | None = None
    mode: str = "full"
    errors: list[AnalysisError] = dc_field(default_factory=list)
    suppressed: dict = dc_field(default_factory=dict)
    cache_stats: dict = dc_field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """False when any file failed to analyze, whatever the findings say."""
        return not self.errors

    @property
    def by_severity(self) -> dict[str, int]:
        """Finding counts per severity, always including all four keys."""
        counts = {s: 0 for s in SEVERITY_ORDER}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    @property
    def by_category(self) -> dict[str, int]:
        """Finding counts per analyzer category."""
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.category] = counts.get(finding.category, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def total_sloc(self) -> int:
        """Total non-blank, non-comment source lines reviewed."""
        return sum(m.sloc for m in self.metrics.values())

    def top_risks(self, limit: int = 10) -> list[Finding]:
        """Highest risk-scored findings (already sorted at build time)."""
        return self.findings[:limit]

    def file_risk(self) -> list[tuple[str, float, int]]:
        """(file, summed risk, finding count) sorted by risk, worst first."""
        agg: dict[str, list[float]] = {}
        for finding in self.findings:
            bucket = agg.setdefault(finding.file, [0.0, 0.0])
            bucket[0] += finding.risk
            bucket[1] += 1
        rows = [(path, vals[0], int(vals[1])) for path, vals in agg.items()]
        rows.sort(key=lambda r: (-r[1], r[0]))
        return rows

    def to_dict(self) -> dict:
        """Full machine-readable report payload."""
        return {
            "root": self.root,
            "mode": self.mode,
            "ok": self.ok,
            "errors": [e.to_dict() for e in self.errors],
            "summary": {
                "files_reviewed": len(self.metrics),
                "sloc": self.total_sloc,
                "findings": len(self.findings),
                "by_severity": self.by_severity,
                "by_category": self.by_category,
                "suppressed": self.suppressed,
                "cache": self.cache_stats,
            },
            "health": self.health.to_dict(),
            "churn": self.churn.to_dict(),
            "diff": self.diff_stat.to_dict() if self.diff_stat else None,
            "findings": [f.to_dict() for f in self.findings],
            "file_risk": [{"file": f, "risk": round(r, 2), "findings": n}
                          for f, r, n in self.file_risk()],
            "duplicates": [p.to_dict() for p in self.duplicate_pairs],
            "metrics": {path: m.to_dict() for path, m in sorted(self.metrics.items())},
            "trace": self.trace,
        }


class ReviewSession:
    """Loads sources, runs analyzer passes on demand, and accumulates findings."""

    def __init__(self, root: str, config: AnalyzerConfig | None = None,
                 files: list[str] | None = None,
                 suppressions: Suppressions | None = None,
                 cache: AnalysisCache | None = None):
        self.root = os.path.abspath(root)
        self.config = config or AnalyzerConfig()
        self.files: list[str] = files if files is not None else iter_python_files(self.root)
        self.suppressions = suppressions or Suppressions()
        self.cache = cache
        self.sources: dict[str, str] = {}
        self.trees: dict[str, ast.Module] = {}
        self.metrics: dict[str, ModuleMetrics] = {}
        self.findings: list[Finding] = []
        self.errors: list[AnalysisError] = []
        self.analyzed: set[str] = set()
        self.duplicate_pairs: list = []
        self.cache_hits = 0
        self.cache_misses = 0
        self._blocks: dict[str, list[CodeBlock]] = {}
        self._seen: set[tuple[str, int, str]] = set()

    # -- loading -----------------------------------------------------------
    def abspath(self, rel: str) -> str:
        """Absolute on-disk path for a repo-relative path, contained under root.

        Every path that reaches this method has at some point come from a diff
        header, a config file, a CLI argument or an LLM tool call, so the
        containment check is not theoretical: without it `../../` escapes the
        review root and the tool reads files nobody asked it to.
        """
        if os.path.isabs(rel) or (len(rel) > 1 and rel[1] == ":"):
            raise InputError("path must be relative to the review root", path=rel)
        target = os.path.normpath(os.path.join(self.root, rel.replace("/", os.sep)))
        try:
            contained = os.path.commonpath([self.root, target]) == self.root
        except ValueError:  # different drives on Windows
            contained = False
        if not contained:
            raise InputError("path escapes the review root", path=rel, root=self.root)
        return target

    def source(self, rel: str) -> str:
        """Read (and cache in memory) one file's text."""
        if rel not in self.sources:
            path = self.abspath(rel)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    self.sources[rel] = fh.read()
            except OSError as exc:
                raise InputError(f"cannot read file: {exc}", path=rel) from exc
        return self.sources[rel]

    def release(self, rel: str) -> None:
        """Drop one file's source and AST once nothing else needs them.

        A repo-scale run used to hold every source string and every AST for the
        whole run; clone detection is the only cross-file consumer, so once it
        has run the per-file state is dead weight.
        """
        self.sources.pop(rel, None)
        self.trees.pop(rel, None)

    def tree(self, rel: str) -> ast.Module | None:
        """Parsed module, or None when the file does not compile."""
        if rel in self.trees:
            return self.trees[rel]
        try:
            parsed = ast.parse(self.source(rel), filename=rel)
        except SyntaxError:
            return None
        self.trees[rel] = parsed
        return parsed

    # -- analysis ----------------------------------------------------------
    def add(self, finding: Finding) -> bool:
        """Append a finding unless an identical file:line:rule is already stored."""
        if finding.key in self._seen:
            return False
        self._seen.add(finding.key)
        self.findings.append(finding)
        return True

    def analyze_file(self, rel: str) -> list[Finding]:
        """Run all four passes on one file (idempotent) and return its findings.

        An analyzer bug is recorded as an AnalysisError and re-raised. Callers
        that must keep going (the batch walk, the agent loop) catch it, but the
        error stays in `self.errors` and forces a non-zero exit, because a
        linter reporting "no findings" after a crash is the worst possible
        failure mode.
        """
        if rel in self.analyzed:
            return [f for f in self.findings if f.file == rel]
        self.analyzed.add(rel)
        source = self.source(rel)
        self.suppressions.register(rel, source)
        cached = self.cache.get_full(rel, source) if self.cache is not None else None
        if cached is not None:
            self.cache_hits += 1
            produced, self.metrics[rel], self._blocks[rel] = cached
            for finding in produced:
                self.add(finding)
            return produced
        self.cache_misses += 1
        tree = self.tree(rel)
        try:
            metrics = module_metrics(rel, source, tree)
            produced = analyze_source(rel, source, self.config, tree)
            self._blocks[rel] = extract_blocks(rel, tree) if tree is not None else []
        except Exception as exc:
            error = AnalysisError(f"{type(exc).__name__}: {exc}", file=rel)
            self.errors.append(error)
            log.error("analyzer failed", extra={"file": rel,
                                                "reason": type(exc).__name__})
            raise error from exc
        self.metrics[rel] = metrics
        if self.cache is not None:
            self.cache.put(rel, source, produced, metrics, self._blocks[rel])
        for finding in produced:
            self.add(finding)
        return produced

    def analyze_all(self) -> None:
        """Analyze every discovered file, continuing past per-file failures."""
        for rel in self.files:
            try:
                self.analyze_file(rel)
            except AnalysisError:
                continue  # already recorded in self.errors; the run exits non-zero
            except InputError as exc:
                self.errors.append(AnalysisError(exc.message, file=rel))

    def blocks(self) -> list[CodeBlock]:
        """Structural token blocks for every analyzed file (clone detection input).

        Token streams are cached alongside findings, so a warm run never reparses
        a file just to compare its shape against the rest of the repository.
        """
        out: list[CodeBlock] = []
        for rel in self.files:
            if rel in self._blocks:
                out.extend(self._blocks[rel])
                continue
            tree = self.tree(rel)
            if tree is not None:
                out.extend(extract_blocks(rel, tree))
        return out

    def scan_duplicates(self) -> int:
        """Detect cross-file clones and record them as findings; returns pair count."""
        self.duplicate_pairs = find_duplicates(self.blocks())
        added = 0
        for finding in duplicate_findings(self.duplicate_pairs):
            if self.add(finding):
                added += 1
        return added

    def record(self, file: str, line: int | str, rule: str, message: str,
               suggestion: str, severity: str = "", category: str = "",
               why: str = "") -> bool:
        """Record a finding derived outside the AST passes (e.g. a text search).

        Every argument here can come from `record_finding`, which under
        `--planner llm` is called with model-generated values. It is therefore
        validated, not trusted: the path must stay inside the review root, the
        line must be an integer, and severity/category must be in vocabulary.
        Out-of-vocabulary values used to pass through and then raise KeyError
        inside the risk model, killing the run after the agent loop had already
        returned.
        """
        rule = str(rule).strip()
        if not rule or len(rule) > 64:
            raise ToolInputError("rule id must be 1-64 characters", rule=rule[:80])
        rel = str(file).replace("\\", "/").strip()
        self.abspath(rel)  # containment check; raises InputError on escape
        try:
            lineno = int(line)
        except (TypeError, ValueError) as exc:
            raise ToolInputError("line must be an integer", line=repr(line)) from exc
        spec: RuleSpec | None = RULES.get(rule)
        sev = (severity or (spec.severity if spec else "medium")).strip().lower()
        cat = (category or (spec.category if spec else "security")).strip().lower()
        if sev not in SEVERITY_ORDER:
            raise ToolInputError("unknown severity", severity=sev,
                                 expected=",".join(SEVERITY_ORDER))
        if cat not in CATEGORIES:
            raise ToolInputError("unknown category", category=cat,
                                 expected=",".join(CATEGORIES))
        reason = why or (spec.why if spec else "")
        return self.add(Finding(file=rel, line=max(1, lineno), rule=rule,
                                severity=sev, message=str(message)[:500],
                                suggestion=str(suggestion)[:500],
                                category=cat, why=str(reason)[:1000]))

    def scan_secrets(self, pattern: str = SECRET_SCAN_RE, max_hits: int = 40) -> int:
        """Search non-Python files for credential assignments; returns hits recorded.

        This is the one capability no AST pass can provide, and it is a plain
        function call rather than something only the agent can reach.
        """
        recorded = 0
        for hit in search_text_files(self.root, pattern, max_hits=max_hits):
            key = hit.text.split("=")[0].split(":")[0].strip() or "credential"
            if self.record(hit.file, hit.line, "hardcoded-secret",
                           f"configuration key '{key[:60]}' holds a literal credential",
                           "move the value to a secret manager, reference it by "
                           "name, and rotate it"):
                recorded += 1
        return recorded

    # -- scoring -----------------------------------------------------------
    def _rank(self, findings: list[Finding], churn: ChurnModel) -> list[Finding]:
        """Score every finding by severity x local complexity x file churn."""
        for finding in findings:
            module = self.metrics.get(finding.file)
            complexity = module.complexity_at(finding.line) if module else 1
            complexity_factor = 1.0 + min(complexity, 30) / 15.0
            churn_factor = 1.0 + churn.normalized(finding.file)
            finding.risk = round(
                SEVERITY_WEIGHT[finding.severity] * complexity_factor * churn_factor, 3)
        return sorted(findings, key=lambda f: (-f.risk, SEVERITY_ORDER[f.severity],
                                               f.file, f.line, f.rule))

    def health(self, findings: list[Finding]) -> HealthScore:
        """Aggregate 0-100 score: severity density, complexity, clones, docs.

        Penalties are capped individually so one pathological dimension cannot
        drive the score to zero and hide the others.
        """
        sloc = max(sum(m.sloc for m in self.metrics.values()), 1)
        weighted = sum(SEVERITY_WEIGHT[f.severity] for f in findings)
        density = weighted / sloc * 100.0
        fns = [fn for m in self.metrics.values() for fn in m.functions]
        avg_complexity = sum(f.complexity for f in fns) / len(fns) if fns else 0.0
        dup_ratio = (2 * len(self.duplicate_pairs) / len(fns)) if fns else 0.0
        public = [f for f in fns if f.is_public]
        doc_coverage = (sum(1 for f in public if f.has_docstring) / len(public)
                        if public else 1.0)
        components = {
            "finding_density": min(55.0, 2.2 * density),
            "complexity": min(20.0, max(0.0, avg_complexity - 4.0) * 4.0),
            "duplication": min(15.0, dup_ratio * 100.0 * 1.5),
            "documentation": min(10.0, (1.0 - doc_coverage) * 20.0),
        }
        score = max(0.0, 100.0 - sum(components.values()))
        grade = next(g for threshold, g in GRADES if score >= threshold)
        components["weighted_severity"] = round(weighted, 2)
        components["sloc"] = float(sloc)
        components["avg_complexity"] = round(avg_complexity, 2)
        components["doc_coverage"] = round(doc_coverage, 3)
        return HealthScore(score, grade, components)

    def finalize(self, trace: str = "", changed: dict[str, set[int]] | None = None,
                 diff_stat: DiffStat | None = None, scope: str = "line",
                 context: int = 0) -> ReviewResult:
        """Suppress, rank, optionally diff-filter, score health and package."""
        churn = build_churn(self.root, self.metrics, changed)
        findings = self.suppressions.apply(list(self.findings))
        mode = "full"
        if changed is not None:
            findings = filter_findings(findings, changed, self.metrics, scope, context)
            mode = "diff"
        ranked = self._rank(findings, churn)
        return ReviewResult(root=self.root, findings=ranked, metrics=dict(self.metrics),
                            health=self.health(ranked), churn=churn,
                            duplicate_pairs=list(self.duplicate_pairs), trace=trace,
                            diff_stat=diff_stat, mode=mode, errors=list(self.errors),
                            suppressed=self.suppressions.to_dict(),
                            cache_stats={"hits": self.cache_hits,
                                         "misses": self.cache_misses})
