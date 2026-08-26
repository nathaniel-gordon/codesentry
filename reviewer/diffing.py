"""Diff-aware review: restrict findings to lines a change actually touched.

Reviewers drown when a tool reports a legacy module's 400 pre-existing issues on
a three-line pull request. Both supported inputs - two directories, or a unified
diff file - are reduced to the same structure: `{path: {new line numbers}}` in the
*head* revision, which is the coordinate system findings already use.
"""
from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass

from .analyzers import Finding
from .metrics import ModuleMetrics

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffStat:
    """Summary of what the compared revisions changed."""

    files_changed: int
    lines_added: int
    files_added: tuple[str, ...]

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {"files_changed": self.files_changed, "lines_added": self.lines_added,
                "files_added": list(self.files_added)}


def iter_python_files(root: str) -> list[str]:
    """Repo-relative POSIX paths of every .py file under `root`, sorted.

    Sorting makes every downstream step (analysis order, agent trace, report
    ordering) reproducible regardless of filesystem enumeration order.
    """
    skip = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache",
            ".pytest_cache", "output", "build", "dist", ".idea", ".tox"}
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, name), root)
                out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def _read(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read().splitlines()


def changed_lines_between(base_root: str, head_root: str) -> tuple[dict[str, set[int]], DiffStat]:
    """Line numbers in `head_root` that differ from `base_root`, per file."""
    base_files = set(iter_python_files(base_root))
    head_files = iter_python_files(head_root)
    changed: dict[str, set[int]] = {}
    added_files: list[str] = []
    total_added = 0
    for rel in head_files:
        head_lines = _read(os.path.join(head_root, rel.replace("/", os.sep)))
        if rel not in base_files:
            added_files.append(rel)
            changed[rel] = set(range(1, len(head_lines) + 1))
            total_added += len(head_lines)
            continue
        base_lines = _read(os.path.join(base_root, rel.replace("/", os.sep)))
        matcher = difflib.SequenceMatcher(None, base_lines, head_lines, autojunk=False)
        touched: set[int] = set()
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "insert"):
                touched.update(range(j1 + 1, j2 + 1))
        if touched:
            changed[rel] = touched
            total_added += len(touched)
    return changed, DiffStat(len(changed), total_added, tuple(sorted(added_files)))


def parse_unified_diff(text: str) -> tuple[dict[str, set[int]], DiffStat]:
    """Extract per-file added/modified line numbers from a unified diff."""
    changed: dict[str, set[int]] = {}
    current: str | None = None
    new_line = 0
    total_added = 0
    for raw in text.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip().split("\t")[0]
            if path in ("/dev/null",):
                current = None
                continue
            if path.startswith(("b/", "a/")):
                path = path[2:]
            current = path.replace("\\", "/")
            changed.setdefault(current, set())
            continue
        if raw.startswith("--- ") or raw.startswith("diff "):
            continue
        hunk = HUNK_RE.match(raw)
        if hunk:
            new_line = int(hunk.group(1))
            continue
        if current is None:
            continue
        if raw.startswith("+"):
            changed[current].add(new_line)
            total_added += 1
            new_line += 1
        elif raw.startswith("-") or raw.startswith("\\"):
            continue
        else:
            new_line += 1
    changed = {k: v for k, v in changed.items() if v and k.endswith(".py")}
    return changed, DiffStat(len(changed), total_added, ())


def unified_text(base_root: str, head_root: str, rel: str) -> str:
    """Render a unified diff for one file (used in the markdown report)."""
    base_path = os.path.join(base_root, rel.replace("/", os.sep))
    head_path = os.path.join(head_root, rel.replace("/", os.sep))
    base_lines = _read(base_path) if os.path.exists(base_path) else []
    head_lines = _read(head_path) if os.path.exists(head_path) else []
    return "\n".join(difflib.unified_diff(base_lines, head_lines,
                                          fromfile=f"a/{rel}", tofile=f"b/{rel}",
                                          lineterm="", n=2))


def filter_findings(findings: list[Finding], changed: dict[str, set[int]],
                    metrics: dict[str, ModuleMetrics] | None = None,
                    scope: str = "line", context: int = 0) -> list[Finding]:
    """Keep only findings the change is responsible for.

    scope='line'     - the finding sits on a changed line (+/- `context`).
    scope='function' - the finding sits in a function that contains a changed
                       line, which catches defects introduced by an edit a few
                       lines above (a new early return breaking a later branch).
    """
    kept: list[Finding] = []
    for finding in findings:
        touched = changed.get(finding.file)
        if not touched:
            continue
        if any(abs(finding.line - line) <= context for line in touched):
            kept.append(finding)
            continue
        if scope == "function" and metrics is not None:
            module = metrics.get(finding.file)
            fn = module.function_at(finding.line) if module else None
            if fn and any(fn.line <= line <= fn.end_line for line in touched):
                kept.append(finding)
    return kept
