"""Report writers: a human markdown review and a machine-readable JSON payload.

Both are generated from the same `ReviewResult`, so the JSON a CI job gates on
and the markdown a human reads can never disagree.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .analyzers import SEVERITY_ORDER
from .review import ReviewResult

SEVERITY_MARK = {"critical": "!!!", "high": "!!", "medium": "!", "low": "."}


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a GitHub-flavoured markdown table."""
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def render_markdown(result: ReviewResult, title: str = "Code Review",
                    max_findings: int = 250, include_trace: bool = True) -> str:
    """Render the full human-facing review."""
    health = result.health
    lines = [
        f"# {title}",
        "",
        f"- **Repository**: `{result.root}`",
        f"- **Mode**: {result.mode}",
        f"- **Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- **Files reviewed**: {len(result.metrics)}  |  **SLOC**: {result.total_sloc}",
        f"- **Churn signal**: {result.churn.source}",
        "",
        f"## Health score: {health.score:.1f}/100 (grade {health.grade})",
        "",
        _table(["penalty", "points"],
               [[k, f"{v:.2f}"] for k, v in health.components.items()
                if k in ("finding_density", "complexity", "duplication", "documentation")]),
        "",
        f"Average cyclomatic complexity {health.components['avg_complexity']}, "
        f"public-API docstring coverage {health.components['doc_coverage']:.0%}, "
        f"weighted severity {health.components['weighted_severity']}.",
        "",
        "## Findings by severity",
        "",
        _table(["severity", "count"],
               [[sev, result.by_severity[sev]] for sev in SEVERITY_ORDER]),
        "",
        "## Findings by category",
        "",
        _table(["category", "count"],
               [[cat, n] for cat, n in result.by_category.items()]) or "_none_",
        "",
    ]
    if result.diff_stat:
        lines += ["## Diff scope", "",
                  f"{result.diff_stat.files_changed} file(s) changed, "
                  f"{result.diff_stat.lines_added} line(s) added or modified.", ""]
    top = result.top_risks(10)
    if top:
        lines += ["## Top risks (severity x complexity x churn)", "",
                  _table(["risk", "severity", "location", "rule", "message"],
                         [[f"{f.risk:.1f}", f.severity, f"`{f.location()}`", f.rule,
                           f.message] for f in top]), ""]
    risky_files = result.file_risk()[:10]
    if risky_files:
        lines += ["## Riskiest files", "",
                  _table(["file", "risk", "findings", "sloc", "max cc"],
                         [[f"`{path}`", f"{risk:.1f}", n,
                           result.metrics[path].sloc if path in result.metrics else "-",
                           result.metrics[path].max_complexity
                           if path in result.metrics else "-"]
                          for path, risk, n in risky_files]), ""]
    lines += ["## Findings", ""]
    if not result.findings:
        lines.append("_No findings._")
    shown = 0
    current_file = ""
    for finding in sorted(result.findings,
                          key=lambda f: (f.file, f.line, SEVERITY_ORDER[f.severity])):
        if shown >= max_findings:
            lines.append(f"\n_({len(result.findings) - shown} further findings omitted)_")
            break
        if finding.file != current_file:
            current_file = finding.file
            lines += ["", f"### `{current_file}`", ""]
        where = f"{finding.file}:{finding.line}"
        scope = f" in `{finding.function}()`" if finding.function else ""
        lines += [
            f"- **[{finding.severity.upper()}] {finding.rule}** - `{where}`{scope}  ",
            f"  {finding.message}  ",
            f"  *Why it matters*: {finding.why}  ",
            f"  *Fix*: {finding.suggestion}",
        ]
        shown += 1
    if result.duplicate_pairs:
        lines += ["", "## Duplicated blocks", "",
                  _table(["similarity", "first", "second"],
                         [[f"{p.similarity:.0%}", f"`{p.a.file}:{p.a.line}` {p.a.name}",
                           f"`{p.b.file}:{p.b.line}` {p.b.name}"]
                          for p in result.duplicate_pairs[:15]]), ""]
    hot = sorted((fn for m in result.metrics.values() for fn in m.functions),
                 key=lambda f: (-f.complexity, f.file, f.line))[:10]
    if hot:
        lines += ["## Complexity hot spots", "",
                  _table(["function", "location", "cc", "nesting", "lines", "params"],
                         [[fn.name, f"`{fn.file}:{fn.line}`", fn.complexity, fn.nesting,
                           fn.length, fn.params] for fn in hot]), ""]
    if include_trace and result.trace:
        lines += ["## Agent investigation trace", "", "```", result.trace, "```", ""]
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
