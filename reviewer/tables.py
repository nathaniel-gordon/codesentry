"""Two table renderers over the same rows: markdown, and aligned plain text.

Both the CLI and the markdown reporter used to build tables their own way (one
via `tabulate`, one by hand). Sharing them removes the project's only
third-party runtime dependency and guarantees the terminal and the report agree
on column order.
"""
from __future__ import annotations

from collections.abc import Sequence


def _cells(row: Sequence[object]) -> list[str]:
    return ["" if c is None else str(c) for c in row]


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """GitHub-flavoured markdown table; pipes in cells are escaped."""
    head = [str(h) for h in headers]
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    for row in rows:
        out.append("| " + " | ".join(c.replace("|", "\\|") for c in _cells(row)) + " |")
    return "\n".join(out)


def text_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """Column-aligned plain-text table for terminal output."""
    head = [str(h) for h in headers]
    body = [_cells(r) for r in rows]
    widths = [len(h) for h in head]
    for row in body:
        for i, cell in enumerate(row[:len(widths)]):
            widths[i] = max(widths[i], len(cell))
    def line(cells: Sequence[str]) -> str:
        padded = [cells[i].ljust(widths[i]) if i < len(cells) else " " * widths[i]
                  for i in range(len(widths))]
        return "  ".join(padded).rstrip()
    out = [line(head), "  ".join("-" * w for w in widths)]
    out.extend(line(row) for row in body)
    return "\n".join(out)
