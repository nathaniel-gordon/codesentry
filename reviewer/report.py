"""Report writers: a human markdown review and a machine-readable JSON payload.

Both are generated from the same `ReviewResult`, so the JSON a CI job gates on
and the markdown a human reads can never disagree.

The markdown is assembled from one section renderer per heading. Each returns
its lines or an empty list when it has nothing to say, which keeps the ordering
of the document in one readable list instead of inside a long branchy function.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from .analyzers import SEVERITY_ORDER
from .review import ReviewResult
from .tables import markdown_table as _table


def _header(result: ReviewResult, title: str) -> list[str]:
    health = result.health
    return [
        f"# {title}", "",
        f"- **Repository**: `{result.root}`",
        f"- **Mode**: {result.mode}",
        f"- **Generated**: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- **Files reviewed**: {len(result.metrics)}  |  **SLOC**: {result.total_sloc}",
        f"- **Churn signal**: {result.churn.source}",
        f"- **Analysis complete**: {'yes' if result.ok else 'NO - see below'}",
        "",
        f"## Health score: {health.score:.1f}/100 (grade {health.grade})", "",
        _table(["penalty", "points"],
               [[k, f"{v:.2f}"] for k, v in health.components.items()
                if k in ("finding_density", "complexity", "duplication",
                         "documentation")]),
        "",
        f"Average cyclomatic complexity {health.components['avg_complexity']}, "
        f"public-API docstring coverage {health.components['doc_coverage']:.0%}, "
        f"weighted severity {health.components['weighted_severity']}.",
        "",
        "## Findings by severity", "",
        _table(["severity", "count"],
               [[sev, result.by_severity[sev]] for sev in SEVERITY_ORDER]),
        "",
        "## Findings by category", "",
        _table(["category", "count"],
               [[cat, n] for cat, n in result.by_category.items()]) or "_none_",
        "",
    ]


def _failures(result: ReviewResult) -> list[str]:
    """Loud and near the top: every count below is missing these files."""
    if not result.errors:
        return []
    return ["## Analyzer failures", "",
            "These files were **not** analyzed, so the counts above are "
            "incomplete and the run exits non-zero.", "",
            _table(["file", "error"],
                   [[f"`{e.file}`", e.message] for e in result.errors]), ""]


def _suppressed(result: ReviewResult) -> list[str]:
    box = result.suppressed
    if not (box.get("by_pragma") or box.get("by_baseline")):
        return []
    return ["## Suppressed", "",
            f"{box.get('by_pragma', 0)} finding(s) silenced by an inline pragma, "
            f"{box.get('by_baseline', 0)} by the baseline "
            f"`{box.get('baseline') or '-'}`.", ""]


def _diff_scope(result: ReviewResult) -> list[str]:
    if not result.diff_stat:
        return []
    return ["## Diff scope", "",
            f"{result.diff_stat.files_changed} file(s) changed, "
            f"{result.diff_stat.lines_added} line(s) added or modified.", ""]


def _top_risks(result: ReviewResult) -> list[str]:
    top = result.top_risks(10)
    if not top:
        return []
    return ["## Top risks (severity x complexity x churn)", "",
            _table(["risk", "severity", "location", "rule", "message"],
                   [[f"{f.risk:.1f}", f.severity, f"`{f.location()}`", f.rule,
                     f.message] for f in top]), ""]


def _riskiest_files(result: ReviewResult) -> list[str]:
    risky = result.file_risk()[:10]
    if not risky:
        return []
    rows = []
    for path, risk, count in risky:
        metrics = result.metrics.get(path)
        rows.append([f"`{path}`", f"{risk:.1f}", count,
                     metrics.sloc if metrics else "-",
                     metrics.max_complexity if metrics else "-"])
    return ["## Riskiest files", "",
            _table(["file", "risk", "findings", "sloc", "max cc"], rows), ""]


def _findings(result: ReviewResult, max_findings: int) -> list[str]:
    lines = ["## Findings", ""]
    if not result.findings:
        return [*lines, "_No findings._"]
    ordered = sorted(result.findings,
                     key=lambda f: (f.file, f.line, SEVERITY_ORDER[f.severity]))
    current_file = ""
    for shown, finding in enumerate(ordered):
        if shown >= max_findings:
            lines.append(f"\n_({len(ordered) - shown} further findings omitted)_")
            break
        if finding.file != current_file:
            current_file = finding.file
            lines += ["", f"### `{current_file}`", ""]
        scope = f" in `{finding.function}()`" if finding.function else ""
        lines += [
            f"- **[{finding.severity.upper()}] {finding.rule}** - "
            f"`{finding.location()}`{scope}  ",
            f"  {finding.message}  ",
            f"  *Why it matters*: {finding.why}  ",
            f"  *Fix*: {finding.suggestion}",
        ]
    return lines


def _duplicates(result: ReviewResult) -> list[str]:
    if not result.duplicate_pairs:
        return []
    return ["", "## Duplicated blocks", "",
            _table(["similarity", "first", "second"],
                   [[f"{p.similarity:.0%}", f"`{p.a.file}:{p.a.line}` {p.a.name}",
                     f"`{p.b.file}:{p.b.line}` {p.b.name}"]
                    for p in result.duplicate_pairs[:15]]), ""]


def _hot_spots(result: ReviewResult) -> list[str]:
    hot = sorted((fn for m in result.metrics.values() for fn in m.functions),
                 key=lambda f: (-f.complexity, f.file, f.line))[:10]
    if not hot:
        return []
    return ["## Complexity hot spots", "",
            _table(["function", "location", "cc", "nesting", "lines", "params"],
                   [[fn.name, f"`{fn.file}:{fn.line}`", fn.complexity, fn.nesting,
                     fn.length, fn.params] for fn in hot]), ""]


def render_markdown(result: ReviewResult, title: str = "Code Review",
                    max_findings: int = 250, include_trace: bool = True) -> str:
    """Render the full human-facing review."""
    lines = [
        *_header(result, title),
        *_failures(result),
        *_suppressed(result),
        *_diff_scope(result),
        *_top_risks(result),
        *_riskiest_files(result),
        *_findings(result, max_findings),
        *_duplicates(result),
        *_hot_spots(result),
    ]
    if include_trace and result.trace:
        lines += ["## Investigation trace", "", "```", result.trace, "```", ""]
    return "\n".join(lines) + "\n"


def write_reports(result: ReviewResult, out_dir: str, stem: str = "review",
                  title: str = "Code Review") -> tuple[str, str]:
    """Write `<stem>.md` and `<stem>.json`; returns both absolute paths."""
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, f"{stem}.md")
    json_path = os.path.join(out_dir, f"{stem}.json")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(render_markdown(result, title=title))
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2, sort_keys=False)
    return os.path.abspath(md_path), os.path.abspath(json_path)
