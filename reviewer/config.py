"""Effective settings: file defaults, then CLI flags on top.

`AnalyzerConfig.skip_rules` has always existed and always been honoured, but
nothing populated it, so there was no way to turn a rule off. This module is
the missing half: it reads `[tool.codesentry]` from the nearest pyproject.toml
and resolves `--pack`, `--select` and `--ignore` into the skip set the analyzer
already understands.

Precedence is the usual one, most specific last:

    built-in defaults  <  [tool.codesentry]  <  command-line flags

Unknown keys and unknown rule ids are `ConfigError`/`UsageError` rather than
warnings. A typo in a rule id would otherwise silently disable nothing, and the
user would believe a rule was off when it was still firing.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace

from .analyzers import PACKS, RULES, SEVERITY_ORDER, AnalyzerConfig
from .errors import ConfigError, UsageError
from .logging_setup import get_logger

log = get_logger("config")

CONFIG_FILENAME = "pyproject.toml"
CONFIG_SECTION = "codesentry"

#: pyproject key -> AnalyzerConfig field. Dashes in TOML, underscores in Python.
THRESHOLD_KEYS = {
    "max-complexity": "max_complexity",
    "max-nesting": "max_nesting",
    "max-fn-lines": "max_fn_lines",
    "max-params": "max_params",
    "max-line-len": "max_line_len",
    "max-imports": "max_imports",
}
LIST_KEYS = ("packs", "select", "ignore", "exclude")
SCALAR_KEYS = ("fail-under", "fail-on-severity", "baseline", "cache")
KNOWN_KEYS = frozenset(THRESHOLD_KEYS) | frozenset(LIST_KEYS) | frozenset(SCALAR_KEYS)


@dataclass(frozen=True)
class Settings:
    """Everything a run needs that a user is allowed to configure."""

    analyzer: AnalyzerConfig = field(default_factory=AnalyzerConfig)
    packs: tuple[str, ...] = tuple(PACKS)
    exclude: tuple[str, ...] = ()
    fail_under: float | None = None
    fail_on_severity: str | None = None
    baseline: str | None = None
    cache: bool = True
    source: str = "<defaults>"

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view, for the report's provenance block."""
        return {
            "source": self.source,
            "packs": list(self.packs),
            "skipped_rules": sorted(self.analyzer.skip_rules),
            "exclude": list(self.exclude),
            "fail_under": self.fail_under,
            "fail_on_severity": self.fail_on_severity,
            "baseline": self.baseline,
            "cache": self.cache,
        }


def find_config(start: str) -> str | None:
    """Nearest pyproject.toml at or above `start`, or None."""
    current = os.path.abspath(start)
    if os.path.isfile(current):
        current = os.path.dirname(current)
    while True:
        candidate = os.path.join(current, CONFIG_FILENAME)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _read_section(path: str) -> dict:
    """The `[tool.codesentry]` table from one pyproject.toml, or {}."""
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read config: {exc}", path=path) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config is not valid TOML: {exc}", path=path) from exc
    section = data.get("tool", {}).get(CONFIG_SECTION, {})
    if not isinstance(section, dict):
        raise ConfigError("[tool.codesentry] must be a table", path=path)
    unknown = sorted(set(section) - KNOWN_KEYS)
    if unknown:
        raise ConfigError("unknown key(s) in [tool.codesentry]", path=path,
                          keys=",".join(unknown), known=",".join(sorted(KNOWN_KEYS)))
    return section


def _str_list(section: dict, key: str, path: str) -> tuple[str, ...] | None:
    if key not in section:
        return None
    value = section[key]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"'{key}' must be a list of strings", path=path)
    return tuple(v.strip() for v in value if v.strip())


def resolve_skip_rules(packs: tuple[str, ...], select: frozenset[str],
                       ignore: frozenset[str]) -> frozenset[str]:
    """Turn pack/select/ignore into the set of rule ids the analyzer must skip.

    `--select` is exclusive: naming any rule means only those rules run, and the
    pack list stops mattering. `--ignore` subtracts from whatever survived.
    """
    for pack in packs:
        if pack not in PACKS:
            raise UsageError("unknown rule pack", pack=pack,
                             known=",".join(sorted(PACKS)))
    unknown = sorted((select | ignore) - set(RULES))
    if unknown:
        raise UsageError("unknown rule id", rules=",".join(unknown))
    if select:
        enabled = set(select)
    else:
        enabled = {rule for pack in packs for rule in PACKS[pack]}
    enabled -= ignore
    return frozenset(set(RULES) - enabled)


def load_settings(root: str, *, use_config: bool = True) -> Settings:
    """Read the nearest pyproject.toml's `[tool.codesentry]` into Settings."""
    if not use_config:
        return Settings()
    path = find_config(root)
    if path is None:
        return Settings()
    section = _read_section(path)
    if not section:
        return Settings(source=path)
    analyzer = AnalyzerConfig()
    for toml_key, field_name in THRESHOLD_KEYS.items():
        if toml_key not in section:
            continue
        value = section[toml_key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ConfigError(f"'{toml_key}' must be a positive integer", path=path,
                              value=repr(value))
        analyzer = replace(analyzer, **{field_name: value})
    packs = _str_list(section, "packs", path) or tuple(PACKS)
    select = frozenset(_str_list(section, "select", path) or ())
    ignore = frozenset(_str_list(section, "ignore", path) or ())
    analyzer = replace(analyzer, skip_rules=resolve_skip_rules(packs, select, ignore))
    severity = section.get("fail-on-severity")
    if severity is not None and severity not in SEVERITY_ORDER:
        raise ConfigError("'fail-on-severity' is not a known severity", path=path,
                          value=repr(severity), expected=",".join(SEVERITY_ORDER))
    fail_under = section.get("fail-under")
    if fail_under is not None and not isinstance(fail_under, (int, float)):
        raise ConfigError("'fail-under' must be a number", path=path,
                          value=repr(fail_under))
    log.debug("loaded config", extra={"path": path, "packs": ",".join(packs)})
    return Settings(
        analyzer=analyzer, packs=packs,
        exclude=_str_list(section, "exclude", path) or (),
        fail_under=float(fail_under) if fail_under is not None else None,
        fail_on_severity=severity,
        baseline=section.get("baseline"),
        cache=bool(section.get("cache", True)),
        source=path,
    )


def apply_overrides(settings: Settings, *, thresholds: dict[str, int | None],
                    packs: tuple[str, ...] | None, select: tuple[str, ...],
                    ignore: tuple[str, ...], fail_under: float | None = None,
                    fail_on_severity: str | None = None,
                    baseline: str | None = None,
                    cache: bool | None = None) -> Settings:
    """Lay explicit command-line flags over file settings.

    A threshold of None means "the flag was not passed", which is why the CLI
    defaults every threshold flag to None instead of to the built-in value:
    otherwise every run would silently override the config file with defaults.
    """
    analyzer = settings.analyzer
    given = {k: v for k, v in thresholds.items() if v is not None}
    for name, value in given.items():
        if value < 1:
            raise UsageError(f"--{name.replace('_', '-')} must be at least 1",
                             value=value)
    if given:
        analyzer = replace(analyzer, **given)
    if packs is not None or select or ignore:
        chosen = packs if packs is not None else settings.packs
        analyzer = replace(analyzer, skip_rules=resolve_skip_rules(
            chosen, frozenset(select), frozenset(ignore)))
        settings = replace(settings, packs=chosen)
    if fail_on_severity is not None and fail_on_severity not in SEVERITY_ORDER:
        raise UsageError("unknown severity", severity=fail_on_severity,
                         expected=",".join(SEVERITY_ORDER))
    return replace(
        settings, analyzer=analyzer,
        fail_under=settings.fail_under if fail_under is None else fail_under,
        fail_on_severity=(settings.fail_on_severity if fail_on_severity is None
                          else fail_on_severity),
        baseline=settings.baseline if baseline is None else baseline,
        cache=settings.cache if cache is None else cache,
    )
