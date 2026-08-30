"""One test per security defect that was fixed, so it cannot come back quietly.

Each test names the fix it guards in its docstring. They are collected here
rather than spread through the suite because these are the assertions that must
survive a refactor of the code they cover: the rest of the suite tests what the
tool does, and this file tests what it must never do.

Sibling coverage lives in test_hardening.py (path containment, tool-argument
validation, regex bounds) and test_cache.py (schema refusal). This file covers
the ones those two do not: subprocess hardening, log redaction, credential
values in reports, and SQL parameterisation.
"""
from __future__ import annotations

import io
import json
import logging
import pickle
import sqlite3

import pytest

from reviewer import churn
from reviewer.__main__ import main
from reviewer.analyzers import AnalyzerConfig, analyze_source
from reviewer.cache import AnalysisCache
from reviewer.errors import EXIT_OK
from reviewer.logging_setup import REDACTED_KEYS, configure_logging, get_logger
from reviewer.metrics import module_metrics


# -- git is run against an untrusted checkout -------------------------------
def test_git_churn_pins_the_config_keys_that_name_programs(tmp_path, monkeypatch):
    """Regression: `git log` in a hostile checkout read its .git/config.

    core.fsmonitor and core.pager name programs git will execute, and hooksPath
    points at scripts it will run. Reviewing an untrusted repository must not be
    a way to get code executed, so all three are pinned on the command line
    where the repository's own config cannot win.
    """
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return type("P", (), {"returncode": 1, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(churn.subprocess, "run", fake_run)
    churn.git_churn(str(tmp_path))
    joined = " ".join(seen["cmd"])
    assert "core.fsmonitor=false" in joined
    assert "core.pager=cat" in joined
    assert "core.hooksPath=/dev/null" in joined


def test_git_churn_never_uses_a_shell(tmp_path, monkeypatch):
    """Regression: the churn command must stay an argv list, never a shell string."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return type("P", (), {"returncode": 1, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(churn.subprocess, "run", fake_run)
    churn.git_churn(str(tmp_path))
    assert isinstance(seen["cmd"], list)
    assert seen["kwargs"].get("shell") in (None, False)
    assert seen["kwargs"].get("timeout")


def test_git_churn_survives_a_repository_that_is_not_one(tmp_path):
    """A directory with no git history yields no churn rather than an exception."""
    assert churn.git_churn(str(tmp_path)) == {}


# -- logs never carry secret values -----------------------------------------
def _capture(fmt: str, **extra) -> str:
    stream = io.StringIO()
    configure_logging("debug", fmt, stream=stream)
    get_logger("test").warning("event", extra=extra)
    logging.getLogger("codesentry").handlers[0].flush()
    return stream.getvalue()


@pytest.mark.parametrize("key", sorted(REDACTED_KEYS))
def test_every_redacted_key_is_redacted_in_text_logs(key):
    """Regression: structured extras were logged verbatim, secrets included."""
    out = _capture("text", **{key: "sk-live-DO-NOT-LOG-THIS"})
    assert "DO-NOT-LOG-THIS" not in out
    assert "***" in out


@pytest.mark.parametrize("key", sorted(REDACTED_KEYS))
def test_every_redacted_key_is_redacted_in_json_logs(key):
    out = _capture("json", **{key: "sk-live-DO-NOT-LOG-THIS"})
    assert "DO-NOT-LOG-THIS" not in out
    assert json.loads(out)[key] == "***"


def test_redaction_is_case_insensitive():
    assert "DO-NOT-LOG-THIS" not in _capture("json", API_KEY="sk-DO-NOT-LOG-THIS")


def test_a_non_secret_extra_is_still_logged():
    assert "reviewer/x.py" in _capture("json", file="reviewer/x.py")


def test_logs_go_to_stderr_so_stdout_stays_pipeable(capsys, tmp_path):
    """Regression: report output on stdout must not be polluted by log records."""
    (tmp_path / "a.py").write_text("x = eval(s)\n", encoding="utf-8")
    assert main(["--log-level", "debug", "review", str(tmp_path),
                 "--stdout", "--format", "json", "--quiet"]) == EXIT_OK
    captured = capsys.readouterr()
    json.loads(captured.out)  # parses, so nothing else was written to stdout


# -- credential values never reach a report ---------------------------------
def test_the_secret_scan_reports_the_key_not_the_value(tmp_path):
    """Regression check: a report is an artifact that gets uploaded and shared.

    The config scan exists to find credentials, so it must name the key and the
    location without copying the credential into markdown, JSON and SARIF.
    """
    (tmp_path / "settings.ini").write_text(
        "[db]\napi_key = AKIA0123456789SECRETVALUE\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    out = tmp_path / "out"
    assert main(["review", str(tmp_path), "--out", str(out), "--quiet",
                 "--format", "json", "--format", "md", "--format", "sarif"]) == EXIT_OK
    for name in ("review.json", "review.md", "review.sarif"):
        body = (out / name).read_text(encoding="utf-8")
        assert "api_key" in body
        assert "AKIA0123456789SECRETVALUE" not in body


# -- the cache is a plain file a hostile repo could replace -----------------
def test_cached_payloads_are_json_text_not_pickle(tmp_path):
    """Regression: unpickling a cache file found in a reviewed tree is RCE."""
    db = tmp_path / "cache.db"
    with AnalysisCache(str(db), AnalyzerConfig()) as cache:
        source = "def f():\n    return eval('1')\n"
        cache.put("a.py", source, analyze_source("a.py", source, AnalyzerConfig()),
                  module_metrics("a.py", source), [])
    conn = sqlite3.connect(db)
    findings, metrics, blocks = conn.execute(
        "SELECT findings, metrics, blocks FROM file_analysis").fetchone()
    conn.close()
    for column in (findings, metrics, blocks):
        assert isinstance(column, str)
        json.loads(column)  # raises if it is anything but JSON


def test_a_pickle_payload_in_the_cache_is_dropped_not_loaded(tmp_path):
    """A row someone rewrote by hand is a miss, and re-analysis is the answer."""
    db = tmp_path / "cache.db"
    source = "x = 1\n"
    with AnalysisCache(str(db), AnalyzerConfig()) as cache:
        cache.put("a.py", source, [], module_metrics("a.py", source), [])
        conn = cache._conn
        conn.execute("UPDATE file_analysis SET findings = ?",
                     (pickle.dumps({"rule": "x"}).hex(),))
        conn.commit()
        assert cache.get_full("a.py", source) is None
        assert cache.stats.misses == 1


def test_a_path_full_of_sql_metacharacters_round_trips(tmp_path):
    """Every statement is parameterised; no identifier is interpolated."""
    db = tmp_path / "cache.db"
    evil = "a'; DROP TABLE file_analysis; --/x.py"
    source = "y = 2\n"
    with AnalysisCache(str(db), AnalyzerConfig()) as cache:
        cache.put(evil, source, [], module_metrics(evil, source), [])
        entry = cache.get_full(evil, source)
        assert entry is not None
        assert cache.summary()["rows"] == 1


# -- rule behaviour that is itself a security decision ----------------------
def test_weak_hash_does_not_fire_when_the_caller_opted_out():
    """`usedforsecurity=False` is the caller stating the hash is not a control."""
    source = ("import hashlib\n"
              "def f(b):\n"
              "    return hashlib.md5(b, usedforsecurity=False).hexdigest()\n")
    rules = {f.rule for f in analyze_source("a.py", source, AnalyzerConfig())}
    assert "weak-hash" not in rules


def test_weak_hash_still_fires_without_the_opt_out():
    source = ("import hashlib\n"
              "def f(b):\n"
              "    return hashlib.md5(b).hexdigest()\n")
    rules = {f.rule for f in analyze_source("a.py", source, AnalyzerConfig())}
    assert "weak-hash" in rules
