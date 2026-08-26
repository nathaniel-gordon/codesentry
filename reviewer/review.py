"""Review session: the mutable store the agent's tools write into, plus scoring.

The agent does not compute results; it *drives* this session. Every tool call
lands here, so a review assembled by the deterministic planner and one assembled
by an LLM planner produce the same shaped result, and the risk model has a single
implementation.
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass

from .analyzers import (SEVERITY_ORDER, SEVERITY_WEIGHT, AnalyzerConfig, Finding,
                        RuleSpec, RULES, analyze_source)
from .churn import ChurnModel, build_churn
from .diffing import DiffStat, filter_findings, iter_python_files
from .duplication import CodeBlock, duplicate_findings, extract_blocks, find_duplicates
from .metrics import ModuleMetrics, module_metrics

GRADES = ((90.0, "A"), (80.0, "B"), (70.0, "C"), (60.0, "D"), (0.0, "F"))


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
            "summary": {
                "files_reviewed": len(self.metrics),
                "sloc": self.total_sloc,
                "findings": len(self.findings),
                "by_severity": self.by_severity,
                "by_category": self.by_category,
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
                 files: list[str] | None = None):
        self.root = os.path.abspath(root)
        self.config = config or AnalyzerConfig()
        self.files: list[str] = files if files is not None else iter_python_files(self.root)
        self.sources: dict[str, str] = {}
        self.trees: dict[str, ast.Module] = {}
        self.metrics: dict[str, ModuleMetrics] = {}
        self.findings: list[Finding] = []
        self.analyzed: set[str] = set()
        self.duplicate_pairs: list = []
        self._seen: set[tuple[str, int, str]] = set()

    # -- loading -----------------------------------------------------------
    def abspath(self, rel: str) -> str:
        """Absolute on-disk path for a repo-relative path."""
        return os.path.join(self.root, rel.replace("/", os.sep))

    def source(self, rel: str) -> str:
        """Read (and cache) one file's text."""
        if rel not in self.sources:
            with open(self.abspath(rel), "r", encoding="utf-8", errors="replace") as fh:
                self.sources[rel] = fh.read()
        return self.sources[rel]

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
        """Run all four passes on one file (idempotent) and return its findings."""
        if rel in self.analyzed:
            return [f for f in self.findings if f.file == rel]
        self.analyzed.add(rel)
        source = self.source(rel)
        tree = self.tree(rel)
        self.metrics[rel] = module_metrics(rel, source, tree)
        produced = analyze_source(rel, source, self.config, tree)
        for finding in produced:
            self.add(finding)
        return produced

    def analyze_all(self) -> None:
        """Analyze every discovered file."""
        for rel in self.files:
            self.analyze_file(rel)

    def blocks(self) -> list[CodeBlock]:
        """Structural token blocks for every parsed file (duplicate detection input)."""
        out: list[CodeBlock] = []
        for rel in self.files:
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

    def record(self, file: str, line: int, rule: str, message: str,
               suggestion: str, severity: str = "", category: str = "",
               why: str = "") -> bool:
        """Record a finding the agent derived itself (e.g. from a text search).

        Known rules inherit their policy from `RULES`; ad-hoc rules must carry
        their own severity so nothing is ever reported without a severity.
        """
        spec: RuleSpec | None = RULES.get(rule)
        sev = severity or (spec.severity if spec else "medium")
        cat = category or (spec.category if spec else "security")
        reason = why or (spec.why if spec else "")
        return self.add(Finding(file=file, line=int(line), rule=rule, severity=sev,
                                message=message, suggestion=suggestion,
                                category=cat, why=reason))

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
        """Rank, optionally diff-filter, score health and package the result."""
        churn = build_churn(self.root, self.metrics, changed)
        findings = list(self.findings)
        mode = "full"
        if changed is not None:
            findings = filter_findings(findings, changed, self.metrics, scope, context)
            mode = "diff"
        ranked = self._rank(findings, churn)
        return ReviewResult(root=self.root, findings=ranked, metrics=dict(self.metrics),
                            health=self.health(ranked), churn=churn,
                            duplicate_pairs=list(self.duplicate_pairs), trace=trace,
                            diff_stat=diff_stat, mode=mode)
