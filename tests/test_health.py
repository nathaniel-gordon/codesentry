"""Liveness and readiness probes, including the failures they exist to catch.

A probe that can only pass is decoration. Each failing case here is one the
container HEALTHCHECK is supposed to catch: a rule table that lost a rule, an
unparseable config, a cache written by a newer build, a read-only output volume.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from reviewer import health
from reviewer.__main__ import main
from reviewer.errors import EXIT_INTERNAL, EXIT_OK


def _by_name(checks):
    return {c.name: c for c in checks}


# -- liveness ---------------------------------------------------------------
def test_liveness_passes_on_this_install():
    assert all(c.passed for c in health.liveness())


def test_liveness_reports_the_rule_table_size():
    detail = _by_name(health.liveness())["rule-table"].detail
    assert "rules in" in detail


def test_liveness_touches_no_files(tmp_path, monkeypatch):
    # cwd somewhere with no pyproject.toml and no cache: liveness must not care.
    monkeypatch.chdir(tmp_path)
    assert health.report(probe="liveness")["status"] == health.OK


def test_a_rule_outside_every_pack_fails_the_probe(monkeypatch):
    packs = {k: frozenset(v) for k, v in health.PACKS.items()}
    victim = sorted(next(iter(packs.values())))[0]
    packs = {k: frozenset(r for r in v if r != victim) for k, v in packs.items()}
    monkeypatch.setattr(health, "PACKS", packs)
    check = _by_name(health.liveness())["rule-packs"]
    assert not check.passed and victim in check.detail


def test_an_out_of_vocabulary_severity_fails_the_probe(monkeypatch):
    rules = dict(health.RULES)
    victim = sorted(rules)[0]
    spec = rules[victim]
    rules[victim] = type(spec)("catastrophic", spec.category, spec.why)
    monkeypatch.setattr(health, "RULES", rules)
    check = _by_name(health.liveness())["rule-vocabulary"]
    assert not check.passed and victim in check.detail


def test_an_empty_rule_table_fails(monkeypatch):
    monkeypatch.setattr(health, "RULES", {})
    assert not _by_name(health.liveness())["rule-table"].passed


# -- readiness --------------------------------------------------------------
def test_readiness_passes_on_a_clean_tree(tmp_path):
    checks = health.readiness(str(tmp_path), output_dir=str(tmp_path / "out"))
    assert all(c.passed for c in checks), [c.to_dict() for c in checks if not c.passed]


def test_readiness_checks_more_than_liveness(tmp_path):
    live = {c.name for c in health.liveness()}
    ready = {c.name for c in health.readiness(str(tmp_path),
                                              output_dir=str(tmp_path / "out"))}
    assert {"config", "cache", "output-writable"} <= ready - live


def test_an_unparseable_config_fails_readiness(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.codesentry\n", encoding="utf-8")
    check = _by_name(health.readiness(str(tmp_path),
                                      output_dir=str(tmp_path / "out")))["config"]
    assert not check.passed


def test_an_unknown_config_key_fails_readiness(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codesentry]\nmax-complexty = 5\n", encoding="utf-8")
    check = _by_name(health.readiness(str(tmp_path),
                                      output_dir=str(tmp_path / "out")))["config"]
    assert not check.passed and "unknown key" in check.detail


def test_a_cache_from_a_newer_build_fails_readiness(tmp_path):
    db = tmp_path / "cache.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, "
                 "applied_at REAL NOT NULL)")
    conn.execute("INSERT INTO schema_version VALUES (99, 0.0)")
    conn.commit()
    conn.close()
    check = _by_name(health.readiness(str(tmp_path), cache_path=str(db),
                                      output_dir=str(tmp_path / "out")))["cache"]
    assert not check.passed and "newer" in check.detail


def test_a_missing_cache_is_not_a_failure(tmp_path):
    check = _by_name(health.readiness(str(tmp_path),
                                      cache_path=str(tmp_path / "nope.db"),
                                      output_dir=str(tmp_path / "out")))["cache"]
    assert check.passed


def test_an_unwritable_output_directory_fails_readiness(tmp_path):
    blocker = tmp_path / "out"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    check = _by_name(health.readiness(str(tmp_path),
                                      output_dir=str(blocker)))["output-writable"]
    assert not check.passed


def test_missing_git_is_skipped_not_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(health.shutil, "which", lambda _name: None)
    check = _by_name(health.readiness(str(tmp_path),
                                      output_dir=str(tmp_path / "out")))["git"]
    assert check.status == health.SKIPPED and check.passed


# -- the command ------------------------------------------------------------
def test_health_command_exits_zero(tmp_path, capsys):
    assert main(["health", str(tmp_path), "--probe", "liveness"]) == EXIT_OK
    assert "readiness" not in capsys.readouterr().out


def test_health_command_emits_json(tmp_path, capsys):
    assert main(["health", str(tmp_path), "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok" and payload["probe"] == "readiness"
    assert {c["name"] for c in payload["checks"]} >= {"python", "config", "cache"}


def test_a_failing_probe_exits_three(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(health, "RULES", {})
    assert main(["health", str(tmp_path), "--probe", "liveness"]) == EXIT_INTERNAL
    assert "rule-table" in capsys.readouterr().err


@pytest.mark.parametrize("probe", ["liveness", "readiness"])
def test_report_names_the_probe_it_ran(tmp_path, probe):
    assert health.report(str(tmp_path), probe=probe)["probe"] == probe
