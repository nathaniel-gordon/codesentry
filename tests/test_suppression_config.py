"""Suppression pragmas, baselines and `[tool.codesentry]` resolution.

These are the adoption path: a repository with 400 existing findings installs
the tool only if it can silence what it has already decided to live with.
"""
from __future__ import annotations

import pytest

from reviewer.analyzers import PACKS, RULES, AnalyzerConfig, analyze_source
from reviewer.config import apply_overrides, find_config, load_settings, resolve_skip_rules
from reviewer.errors import ConfigError, UsageError
from reviewer.suppression import Baseline, Suppressions, parse_pragmas, unknown_pragma_rules

HEADER = '"""Module."""\n\n\n'
BODY = 'def run(text):\n    """Run."""\n    return eval(text)\n'


def findings(source):
    """Analyze a snippet with a module docstring already in place."""
    return analyze_source("m.py", HEADER + source)


def suppressed(source):
    """Findings left after applying the source's own pragmas."""
    text = HEADER + source
    box = Suppressions()
    box.register("m.py", text)
    return box.apply(analyze_source("m.py", text))


# -- inline pragmas --------------------------------------------------------
def test_bare_pragma_silences_the_line():
    assert findings(BODY)
    assert suppressed('def run(text):\n    """Run."""\n'
                      '    return eval(text)  # codesentry: ignore\n') == []


def test_named_pragma_silences_only_that_rule():
    src = ('def run(text):\n    """Run."""\n'
           '    return eval(text)  # codesentry: ignore[eval-exec]\n')
    assert [f.rule for f in suppressed(src)] == []


def test_named_pragma_for_another_rule_does_not_silence():
    src = ('def run(text):\n    """Run."""\n'
           '    return eval(text)  # codesentry: ignore[weak-hash]\n')
    assert "eval-exec" in [f.rule for f in suppressed(src)]


def test_pragma_on_the_line_above_applies():
    src = ('def run(text):\n    """Run."""\n'
           '    # codesentry: ignore[eval-exec]\n    return eval(text)\n')
    assert "eval-exec" not in [f.rule for f in suppressed(src)]


def test_file_wide_pragma_silences_everything():
    src = ('# codesentry: ignore-file\n'
           'def run(text):\n    """Run."""\n    return eval(text)\n')
    assert suppressed(src) == []


def test_pragma_parsing_is_case_insensitive():
    pragmas = parse_pragmas("x = 1  # CodeSentry: Ignore[eval-exec]\n")
    assert pragmas.silences(1, "eval-exec")


def test_typo_in_a_pragma_rule_is_detectable():
    assert unknown_pragma_rules("x = 1  # codesentry: ignore[eval-exeq]\n") == {
        "eval-exeq"}
    assert unknown_pragma_rules("x = 1  # codesentry: ignore[eval-exec]\n") == set()


# -- baselines -------------------------------------------------------------
def test_baseline_round_trip(tmp_path):
    produced = findings(BODY)
    path = Baseline.from_findings(produced).write(str(tmp_path / "b.json"))
    loaded = Baseline.load(path)
    assert all(loaded.contains(f) for f in produced)


def test_baseline_only_hides_what_it_lists(tmp_path):
    produced = findings(BODY)
    path = Baseline.from_findings(produced).write(str(tmp_path / "b.json"))
    box = Suppressions(baseline=Baseline.load(path))
    fresh = analyze_source("m.py", HEADER + BODY + '\n\ndef more(t):\n'
                           '    """More."""\n    return eval(t)\n')
    kept = box.apply(fresh)
    assert kept, "a defect added after the baseline must still be reported"
    assert box.by_baseline == len(produced)


def test_malformed_baseline_is_a_config_error(tmp_path):
    bad = tmp_path / "b.json"
    bad.write_text('{"findings": [{"file": "m.py"}]}', encoding="utf-8")
    with pytest.raises(ConfigError):
        Baseline.load(str(bad))


def test_unparseable_baseline_is_a_config_error(tmp_path):
    bad = tmp_path / "b.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        Baseline.load(str(bad))


# -- rule selection --------------------------------------------------------
def test_packs_partition_the_rule_table():
    assert set().union(*PACKS.values()) == set(RULES)
    assert sum(len(p) for p in PACKS.values()) == len(RULES)


def test_selecting_one_rule_disables_the_rest():
    skip = resolve_skip_rules(tuple(PACKS), frozenset({"eval-exec"}), frozenset())
    assert skip == frozenset(set(RULES) - {"eval-exec"})


def test_one_pack_disables_the_others():
    skip = resolve_skip_rules(("security",), frozenset(), frozenset())
    assert skip & PACKS["security"] == frozenset()
    assert PACKS["complexity"] <= skip


def test_ignore_subtracts_from_the_selection():
    skip = resolve_skip_rules(("security",), frozenset(), frozenset({"eval-exec"}))
    assert "eval-exec" in skip


def test_unknown_rule_id_is_a_usage_error():
    with pytest.raises(UsageError):
        resolve_skip_rules(tuple(PACKS), frozenset(), frozenset({"no-such-rule"}))


def test_unknown_pack_is_a_usage_error():
    with pytest.raises(UsageError):
        resolve_skip_rules(("nonsense",), frozenset(), frozenset())


def test_skip_rules_actually_suppresses_the_rule():
    config = AnalyzerConfig(skip_rules=frozenset({"eval-exec"}))
    reported = [f.rule for f in analyze_source("m.py", HEADER + BODY, config)]
    assert "eval-exec" not in reported


# -- config file -----------------------------------------------------------
def _write(tmp_path, body):
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    return str(tmp_path)


def test_thresholds_are_read_from_pyproject(tmp_path):
    root = _write(tmp_path, "[tool.codesentry]\nmax-complexity = 3\n")
    assert load_settings(root).analyzer.max_complexity == 3


def test_ignore_list_is_read_from_pyproject(tmp_path):
    root = _write(tmp_path, '[tool.codesentry]\nignore = ["eval-exec"]\n')
    assert "eval-exec" in load_settings(root).analyzer.skip_rules


def test_unknown_key_is_a_config_error(tmp_path):
    root = _write(tmp_path, "[tool.codesentry]\nmax-complexitty = 3\n")
    with pytest.raises(ConfigError):
        load_settings(root)


def test_invalid_threshold_type_is_a_config_error(tmp_path):
    root = _write(tmp_path, '[tool.codesentry]\nmax-complexity = "ten"\n')
    with pytest.raises(ConfigError):
        load_settings(root)


def test_invalid_toml_is_a_config_error(tmp_path):
    root = _write(tmp_path, "[tool.codesentry\n")
    with pytest.raises(ConfigError):
        load_settings(root)


def test_no_config_flag_ignores_the_file(tmp_path):
    root = _write(tmp_path, "[tool.codesentry]\nmax-complexity = 3\n")
    assert load_settings(root, use_config=False).analyzer.max_complexity == 10


def test_config_is_found_from_a_subdirectory(tmp_path):
    _write(tmp_path, "[tool.codesentry]\nmax-complexity = 3\n")
    nested = tmp_path / "pkg" / "sub"
    nested.mkdir(parents=True)
    assert find_config(str(nested)) == str(tmp_path / "pyproject.toml")


def test_command_line_beats_the_config_file(tmp_path):
    root = _write(tmp_path, "[tool.codesentry]\nmax-complexity = 3\n")
    settings = load_settings(root)
    merged = apply_overrides(settings, thresholds={"max_complexity": 20},
                             packs=None, select=(), ignore=())
    assert merged.analyzer.max_complexity == 20


def test_absent_flags_leave_the_config_alone(tmp_path):
    root = _write(tmp_path, "[tool.codesentry]\nmax-complexity = 3\n")
    settings = load_settings(root)
    merged = apply_overrides(settings, thresholds={"max_complexity": None},
                             packs=None, select=(), ignore=())
    assert merged.analyzer.max_complexity == 3


def test_zero_threshold_is_a_usage_error(tmp_path):
    with pytest.raises(UsageError):
        apply_overrides(load_settings(str(tmp_path)),
                        thresholds={"max_nesting": 0}, packs=None, select=(),
                        ignore=())
