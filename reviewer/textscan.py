"""Bounded regex search over the non-Python files an AST pass cannot read.

Credentials live in `settings.ini` and `.env` as often as in `.py`, so the tool
needs a text path. That path takes a caller-supplied pattern, and under
`--planner llm` the caller is a language model, which makes the pattern
untrusted input. Everything here is therefore bounded:

* the pattern has a length cap and is rejected outright for the classic
  catastrophic-backtracking shape (a quantified group that is itself
  quantified);
* only allowlisted text extensions are opened, never `include="all"`;
* per-file bytes, per-line characters, total files and total matches are capped;
* the whole scan carries a wall-clock deadline, checked between lines.

The deadline cannot interrupt a single `re.search` call, so a pathological
pattern on one long line can still overrun it. The line-length cap is what keeps
that bounded in practice, and the residual risk is stated in the README.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from .errors import ToolInputError
from .logging_setup import get_logger

log = get_logger("textscan")

#: Extensions worth searching for credentials. `include="all"` used to open
#: binaries and multi-GB logs; there is no such mode any more.
TEXT_SUFFIXES = (".ini", ".cfg", ".conf", ".env", ".toml", ".yaml", ".yml",
                 ".json", ".properties", ".txt", ".sh", ".service", ".tf")
SKIP_DIRS = frozenset({".git", "__pycache__", "output", ".venv", "venv",
                       "node_modules", ".mypy_cache", ".pytest_cache", "build",
                       "dist", ".tox", ".codesentry-cache"})

MAX_PATTERN_LEN = 200
MAX_FILE_BYTES = 1 << 20        # 1 MiB
MAX_LINE_CHARS = 2000
MAX_FILES = 2000
DEFAULT_DEADLINE_S = 10.0

#: A group that ends in a quantifier and is itself quantified: (a+)+, (\d*)*.
NESTED_QUANTIFIER_RE = re.compile(r"\((?:[^()\\]|\\.)*[+*][)?]?\)\s*[+*]|"
                                  r"\((?:[^()\\]|\\.)*\|(?:[^()\\]|\\.)*\)\s*[+*]\+")


@dataclass(frozen=True)
class TextHit:
    """One regex match: where it was, and the (truncated) line that matched."""

    file: str
    line: int
    text: str

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {"file": self.file, "line": self.line, "text": self.text}


def safe_compile(pattern: str) -> re.Pattern[str]:
    """Compile a caller-supplied pattern, rejecting the unbounded shapes.

    Raises ToolInputError rather than re.error so the caller reports a typed
    failure instead of a traceback.
    """
    if not isinstance(pattern, str) or not pattern:
        raise ToolInputError("search pattern must be a non-empty string")
    if len(pattern) > MAX_PATTERN_LEN:
        raise ToolInputError("search pattern is too long",
                             length=len(pattern), limit=MAX_PATTERN_LEN)
    if NESTED_QUANTIFIER_RE.search(pattern):
        raise ToolInputError(
            "search pattern nests a quantified group inside another quantifier, "
            "which can backtrack exponentially")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ToolInputError(f"invalid regex: {exc}") from exc


def iter_text_files(root: str, limit: int = MAX_FILES) -> list[str]:
    """Repo-relative POSIX paths of the searchable text files under `root`."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(TEXT_SUFFIXES):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            out.append(rel.replace(os.sep, "/"))
            if len(out) >= limit:
                return sorted(out)
    return sorted(out)


def search_text_files(root: str, pattern: str, max_hits: int = 40,
                      deadline_s: float = DEFAULT_DEADLINE_S) -> list[TextHit]:
    """Search the text files under `root`, returning at most `max_hits` matches."""
    rx = safe_compile(pattern)
    stop_at = time.monotonic() + deadline_s
    hits: list[TextHit] = []
    for rel in iter_text_files(root):
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                log.debug("skipping oversized file", extra={"file": rel})
                continue
            with open(path, encoding="utf-8", errors="replace") as handle:
                for lineno, line in enumerate(handle, 1):
                    if time.monotonic() > stop_at:
                        log.warning("text scan deadline reached",
                                    extra={"file": rel, "hits": len(hits)})
                        return hits
                    if rx.search(line[:MAX_LINE_CHARS]):
                        hits.append(TextHit(rel, lineno, line.strip()[:120]))
                        if len(hits) >= max_hits:
                            return hits
        except OSError as exc:
            log.debug("unreadable file skipped", extra={"file": rel, "reason": str(exc)})
            continue
    return hits
