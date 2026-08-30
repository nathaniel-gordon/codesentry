"""Liveness and readiness checks for a codesentry install.

A container needs something to run in its HEALTHCHECK, and a CI job needs a way
to tell "the tool is broken" from "the tool found problems" before it spends ten
minutes analyzing a monorepo. Both are the same question asked at two depths:

    liveness   can this process do anything at all? Import the rule table and
               check it is internally consistent. No filesystem, no subprocess.
    readiness  can this process review the tree in front of it? The config file
               parses, the cache opens at a schema this build understands, and
               the report directory is writable.

Liveness failing means the install is broken. Readiness failing means the
environment is wrong - a corrupt cache, an unparseable pyproject.toml, a
read-only output volume - which is a configuration problem the operator fixes,
not a bug.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass

from . import __version__
from .analyzers import CATEGORIES, PACKS, RULES, SEVERITY_ORDER
from .cache import ANALYZER_VERSION, SCHEMA_VERSION, AnalysisCache, default_cache_path
from .errors import CodeSentryError

OK = "ok"
FAIL = "fail"
SKIPPED = "skipped"


@dataclass(frozen=True)
class Check:
    """One health probe: what it looked at, whether it passed, and why."""

    name: str
    status: str
    detail: str = ""

    @property
    def passed(self) -> bool:
        """True unless the check actively failed (skipped is not a failure)."""
        return self.status != FAIL

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {"name": self.name, "status": self.status, "detail": self.detail}


def _check_rule_table() -> list[Check]:
    """The rule table is the tool: if it is inconsistent nothing downstream works."""
    checks: list[Check] = []
    if not RULES:
        return [Check("rule-table", FAIL, "the rule table is empty")]
    checks.append(Check("rule-table", OK,
                        f"{len(RULES)} rules in {len(PACKS)} packs"))

    packed = [rule for members in PACKS.values() for rule in members]
    unpacked = sorted(set(RULES) - set(packed))
    duplicated = sorted({r for r in packed if packed.count(r) > 1})
    if unpacked or duplicated:
        detail = []
        if unpacked:
            detail.append(f"not in any pack: {', '.join(unpacked)}")
        if duplicated:
            detail.append(f"in more than one pack: {', '.join(duplicated)}")
        checks.append(Check("rule-packs", FAIL, "; ".join(detail)))
    else:
        checks.append(Check("rule-packs", OK, "every rule is in exactly one pack"))

    bad = sorted(rid for rid, spec in RULES.items()
                 if spec.severity not in SEVERITY_ORDER or spec.category not in CATEGORIES)
    checks.append(Check("rule-vocabulary", FAIL if bad else OK,
                        f"out of vocabulary: {', '.join(bad)}" if bad
                        else "severities and categories are in vocabulary"))
    return checks


def liveness() -> list[Check]:
    """Cheap in-process checks. No filesystem, no subprocess, no network."""
    checks = [Check("python", OK,
                    f"{sys.version_info.major}.{sys.version_info.minor}."
                    f"{sys.version_info.micro}")]
    checks.extend(_check_rule_table())
    return checks


def _check_config(root: str) -> Check:
    """[tool.codesentry] in the nearest pyproject.toml parses and validates."""
    from .config import load_settings

    try:
        settings = load_settings(root)
    except CodeSentryError as exc:
        return Check("config", FAIL, str(exc))
    return Check("config", OK, settings.source)


def _check_cache(root: str, cache_path: str | None) -> Check:
    """The cache file opens and its schema is one this build can migrate."""
    path = cache_path or default_cache_path(root)
    if not os.path.exists(path):
        return Check("cache", OK, f"no cache yet at {path} (it is created on demand)")
    try:
        from .analyzers import AnalyzerConfig
        with AnalysisCache(path, AnalyzerConfig()) as cache:
            summary = cache.summary()
    except CodeSentryError as exc:
        return Check("cache", FAIL, str(exc))
    return Check("cache", OK,
                 f"schema v{summary['schema_version']} (build supports "
                 f"v{SCHEMA_VERSION}), {summary['rows']} row(s)")


def _check_writable(path: str) -> Check:
    """The report directory can actually be written to."""
    try:
        os.makedirs(path, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".codesentry-health-",
                                         delete=True):
            pass
    except OSError as exc:
        return Check("output-writable", FAIL, f"{path}: {exc}")
    return Check("output-writable", OK, path)


def _check_git() -> Check:
    """git is optional: without it churn falls back to the static proxy."""
    found = shutil.which("git")
    if found is None:
        return Check("git", SKIPPED,
                     "git not on PATH; churn falls back to the static proxy")
    return Check("git", OK, found)


def readiness(root: str = ".", cache_path: str | None = None,
              output_dir: str | None = None) -> list[Check]:
    """Everything liveness checks, plus the environment this run needs."""
    from .pipeline import default_output_dir

    checks = liveness()
    checks.append(_check_config(root))
    checks.append(_check_cache(root, cache_path))
    checks.append(_check_writable(output_dir or default_output_dir()))
    checks.append(_check_git())
    return checks


def report(root: str = ".", cache_path: str | None = None,
           output_dir: str | None = None, probe: str = "readiness") -> dict:
    """Run the requested probe and package it for printing or JSON output."""
    checks = (liveness() if probe == "liveness"
              else readiness(root, cache_path, output_dir))
    failed = [c for c in checks if not c.passed]
    return {
        "status": OK if not failed else FAIL,
        "probe": probe,
        "version": __version__,
        "analyzer_version": ANALYZER_VERSION,
        "checks": [c.to_dict() for c in checks],
        "failed": [c.name for c in failed],
    }
