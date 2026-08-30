"""Inline pragmas and baseline files: how an existing repo adopts the tool.

Without a suppression story a linter that reports 400 findings on first run gets
uninstalled the same afternoon. Two mechanisms, deliberately no more:

* `# codesentry: ignore[rule-id, other-rule]` on the offending line, or on the
  line above it, or bare (`# codesentry: ignore`) to silence every rule there.
  A file-wide form (`# codesentry: ignore-file[...]`) sits anywhere in the file.
* a baseline JSON file listing `file:line:rule` triples that were already
  present when the tool was adopted, so only *new* findings fail the build.

Both are applied after analysis rather than inside it, so the cache stores the
unfiltered result and changing a pragma does not require a re-analysis of
anything except the file whose text changed.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from .analyzers import RULES, Finding
from .errors import ConfigError
from .logging_setup import get_logger

log = get_logger("suppression")

PRAGMA_RE = re.compile(
    r"#\s*codesentry\s*:\s*ignore(?P<scope>-file)?\s*(?:\[(?P<rules>[^\]]*)\])?",
    re.IGNORECASE)

BASELINE_VERSION = 1


def _split_rules(raw: str | None) -> frozenset[str] | None:
    """Parse the bracketed rule list; None means 'every rule on this line'."""
    if raw is None:
        return None
    ids = frozenset(part.strip() for part in raw.split(",") if part.strip())
    return ids or None


#: Sentinel for a bare `# codesentry: ignore` - every rule, not a named subset.
ALL_RULES: frozenset[str] = frozenset()


def _merge(existing: frozenset[str] | None,
           incoming: frozenset[str] | None) -> frozenset[str] | None:
    """Union two rule selections, where None ('all rules') absorbs anything."""
    if existing is None or incoming is None:
        return None
    return existing | incoming


@dataclass
class FilePragmas:
    """The pragmas found in one file. A None value means 'every rule'."""

    file_wide: dict[str, frozenset[str] | None] = field(default_factory=dict)
    per_line: dict[int, frozenset[str] | None] = field(default_factory=dict)

    def silences(self, line: int, rule: str) -> bool:
        """True when a pragma in this file suppresses `rule` at `line`."""
        if "all" in self.file_wide:
            allowed = self.file_wide["all"]
            if allowed is None or rule in allowed:
                return True
        # A pragma on line N covers N and N+1, so it can sit on the offending
        # line or on the line above it.
        for candidate in (line, line - 1):
            if candidate in self.per_line:
                allowed = self.per_line[candidate]
                if allowed is None or rule in allowed:
                    return True
        return False


def parse_pragmas(source: str) -> FilePragmas:
    """Collect every `# codesentry: ignore` pragma in one file's text."""
    pragmas = FilePragmas()
    for lineno, text in enumerate(source.splitlines(), 1):
        match = PRAGMA_RE.search(text)
        if not match:
            continue
        rules = _split_rules(match.group("rules"))
        if match.group("scope"):
            pragmas.file_wide["all"] = _merge(pragmas.file_wide.get("all", ALL_RULES),
                                              rules)
        else:
            pragmas.per_line[lineno] = _merge(
                pragmas.per_line.get(lineno, ALL_RULES), rules)
    return pragmas


def unknown_pragma_rules(source: str) -> set[str]:
    """Rule ids named in pragmas that no rule table entry defines (typos)."""
    named: set[str] = set()
    for match in PRAGMA_RE.finditer(source):
        named.update(_split_rules(match.group("rules")) or ())
    return {rule for rule in named if rule not in RULES}


@dataclass
class Baseline:
    """Findings that already existed when the tool was adopted."""

    keys: frozenset[tuple[str, int, str]] = frozenset()
    path: str = ""

    def contains(self, finding: Finding) -> bool:
        """True when this exact file:line:rule was in the baseline."""
        return finding.key in self.keys

    @classmethod
    def load(cls, path: str) -> Baseline:
        """Read a baseline file written by `codesentry baseline`."""
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except OSError as exc:
            raise ConfigError(f"cannot read baseline: {exc}", path=path) from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"baseline is not valid JSON: {exc}", path=path) from exc
        if not isinstance(data, dict) or "findings" not in data:
            raise ConfigError("baseline file has no 'findings' list", path=path)
        keys: set[tuple[str, int, str]] = set()
        for row in data["findings"]:
            try:
                keys.add((str(row["file"]), int(row["line"]), str(row["rule"])))
            except (KeyError, TypeError, ValueError) as exc:
                raise ConfigError(f"malformed baseline entry: {row!r}",
                                  path=path) from exc
        return cls(frozenset(keys), os.path.abspath(path))

    @classmethod
    def from_findings(cls, findings: list[Finding]) -> Baseline:
        """Build a baseline covering everything currently reported."""
        return cls(frozenset(f.key for f in findings))

    def write(self, path: str) -> str:
        """Write the baseline as JSON; returns the absolute path."""
        payload = {
            "version": BASELINE_VERSION,
            "findings": [{"file": f, "line": ln, "rule": r}
                         for f, ln, r in sorted(self.keys)],
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        return os.path.abspath(path)


@dataclass
class Suppressions:
    """Applies pragmas and a baseline to a finding list, counting what it removed."""

    pragmas: dict[str, FilePragmas] = field(default_factory=dict)
    baseline: Baseline | None = None
    by_pragma: int = 0
    by_baseline: int = 0

    def register(self, file: str, source: str) -> None:
        """Record the pragmas found in one analyzed file."""
        self.pragmas[file] = parse_pragmas(source)

    def apply(self, findings: list[Finding]) -> list[Finding]:
        """Drop suppressed findings, updating the two counters."""
        kept: list[Finding] = []
        for finding in findings:
            pragma = self.pragmas.get(finding.file)
            if pragma is not None and pragma.silences(finding.line, finding.rule):
                self.by_pragma += 1
                continue
            if self.baseline is not None and self.baseline.contains(finding):
                self.by_baseline += 1
                continue
            kept.append(finding)
        if self.by_pragma or self.by_baseline:
            log.info("suppressed findings",
                     extra={"by_pragma": self.by_pragma,
                            "by_baseline": self.by_baseline})
        return kept

    def to_dict(self) -> dict:
        """Return a JSON-serialisable summary for the report payload."""
        return {"by_pragma": self.by_pragma, "by_baseline": self.by_baseline,
                "baseline": self.baseline.path if self.baseline else None}
