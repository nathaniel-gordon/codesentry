"""End-to-end runs through a real subprocess, plus the metrics dump.

The rest of the suite calls `main()` in-process, which is fast but shares the
interpreter's state: an import that only works because pytest already put the
repo on sys.path, a cache connection that is still open, a registry left over
from the previous test. These tests spend the process start-up to check the
thing an operator actually runs - `python -m reviewer ...` - including the exit
code it hands back to the shell.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

CLEAN = "def add(a, b):\n    \"\"\"Sum two numbers.\"\"\"\n    return a + b\n"
DIRTY = ("import subprocess\n\n\n"
         "def run(cmd):\n"
         '    """Run a command."""\n'
         "    return subprocess.run(cmd, shell=True)\n")


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI the way a shell would, from a clean interpreter."""
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "reviewer", *args],
                          capture_output=True, text=True, timeout=300,
                          cwd=str(cwd or ROOT), env=env, check=False)


@pytest.fixture()
def tree(tmp_path):
    """A two-file project: one clean file, one with a critical finding."""
    (tmp_path / "clean.py").write_text(CLEAN, encoding="utf-8")
    (tmp_path / "dirty.py").write_text(DIRTY, encoding="utf-8")
    return tmp_path


# -- the exit-code contract, observed from a shell ---------------------------
def test_a_clean_tree_exits_zero(tmp_path):
    (tmp_path / "clean.py").write_text(CLEAN, encoding="utf-8")
    proc = run_cli("review", str(tmp_path), "--quiet", "--stdout",
                   "--format", "json", "--fail-on-severity", "high")
    assert proc.returncode == 0, proc.stderr


def test_a_critical_finding_trips_the_gate(tree):
    proc = run_cli("review", str(tree), "--quiet", "--stdout", "--format", "json",
                   "--fail-on-severity", "high")
    assert proc.returncode == 1
    assert "FAIL" in proc.stderr


def test_a_missing_path_exits_two(tmp_path):
    proc = run_cli("review", str(tmp_path / "nope"))
    assert proc.returncode == 2
    assert "input:" in proc.stderr


def test_help_exits_zero():
    assert run_cli("--help").returncode == 0


def test_health_probe_exits_zero_from_a_shell(tmp_path):
    proc = run_cli("health", str(tmp_path), "--probe", "liveness", "--json")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["status"] == "ok"


# -- the reporters agree with each other ------------------------------------
def test_the_three_formats_describe_the_same_run(tree, tmp_path):
    out = tmp_path / "reports"
    proc = run_cli("review", str(tree), "--out", str(out), "--quiet",
                   "--format", "json", "--format", "md", "--format", "sarif")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((out / "review.json").read_text(encoding="utf-8"))
    sarif = json.loads((out / "review.sarif").read_text(encoding="utf-8"))
    markdown = (out / "review.md").read_text(encoding="utf-8")
    assert len(sarif["runs"][0]["results"]) == len(payload["findings"])
    assert payload["summary"]["files_reviewed"] == 2
    for finding in payload["findings"]:
        assert finding["rule"] in markdown


def test_the_report_records_the_run_id_that_produced_it(tree, tmp_path):
    out = tmp_path / "reports"
    run_cli("review", str(tree), "--out", str(out), "--quiet", "--format", "json")
    payload = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert len(payload["run_id"]) == 12


# -- the cache survives process boundaries ----------------------------------
def test_a_second_process_reuses_the_first_one_s_cache(tree, tmp_path):
    db = tmp_path / "cache.db"
    out = tmp_path / "reports"
    cold = run_cli("review", str(tree), "--cache-path", str(db), "--out", str(out),
                   "--quiet", "--format", "json")
    assert cold.returncode == 0, cold.stderr
    first = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert first["summary"]["cache"] == {"hits": 0, "misses": 2}

    warm = run_cli("review", str(tree), "--cache-path", str(db), "--out", str(out),
                   "--quiet", "--format", "json")
    assert warm.returncode == 0, warm.stderr
    second = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert second["summary"]["cache"] == {"hits": 2, "misses": 0}
    assert second["findings"] == first["findings"]


def test_editing_a_file_invalidates_only_that_file(tree, tmp_path):
    db = tmp_path / "cache.db"
    out = tmp_path / "reports"
    run_cli("review", str(tree), "--cache-path", str(db), "--out", str(out),
            "--quiet", "--format", "json")
    (tree / "clean.py").write_text(CLEAN + "\n\n" + CLEAN.replace("add", "sub"),
                                   encoding="utf-8")
    run_cli("review", str(tree), "--cache-path", str(db), "--out", str(out),
            "--quiet", "--format", "json")
    payload = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert payload["summary"]["cache"] == {"hits": 1, "misses": 1}


def test_the_cache_command_sees_what_the_review_wrote(tree, tmp_path):
    db = tmp_path / "cache.db"
    run_cli("review", str(tree), "--cache-path", str(db), "--quiet",
            "--out", str(tmp_path / "r"), "--format", "json")
    proc = run_cli("cache", str(tree), "--cache-path", str(db))
    assert proc.returncode == 0
    assert "rows" in proc.stdout and "schema_version" in proc.stdout


# -- the metrics dump reflects the run that produced it ---------------------
def test_metrics_dump_counts_the_files_the_report_counted(tree, tmp_path):
    out = tmp_path / "reports"
    metrics = tmp_path / "run.prom"
    proc = run_cli("review", str(tree), "--out", str(out), "--quiet",
                   "--format", "json", "--metrics-out", str(metrics))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((out / "review.json").read_text(encoding="utf-8"))
    body = metrics.read_text(encoding="utf-8")
    analyzed = sum(float(line.rsplit(" ", 1)[1]) for line in body.splitlines()
                   if line.startswith("codesentry_files_analyzed_total{"))
    assert analyzed == payload["summary"]["files_reviewed"]
    assert "codesentry_run_duration_ms_count" in body
    assert 'codesentry_phase_duration_ms_bucket{phase="analyze"' in body


def test_metrics_dump_counts_findings_by_severity(tree, tmp_path):
    out = tmp_path / "reports"
    metrics = tmp_path / "run.json"
    run_cli("review", str(tree), "--out", str(out), "--quiet", "--format", "json",
            "--metrics-out", str(metrics))
    payload = json.loads((out / "review.json").read_text(encoding="utf-8"))
    dumped = json.loads(metrics.read_text(encoding="utf-8"))
    series = dumped["counters"]["codesentry_findings_total"]["series"]
    per_severity: dict[str, float] = {}
    for entry in series:
        severity = entry["labels"]["severity"]
        per_severity[severity] = per_severity.get(severity, 0.0) + entry["value"]
    for severity, count in payload["summary"]["by_severity"].items():
        assert per_severity.get(severity, 0.0) == count


def test_a_quiet_run_still_declares_every_series(tmp_path):
    (tmp_path / "clean.py").write_text(CLEAN, encoding="utf-8")
    metrics = tmp_path / "run.prom"
    run_cli("review", str(tmp_path), "--quiet", "--stdout", "--format", "json",
            "--metrics-out", str(metrics))
    body = metrics.read_text(encoding="utf-8")
    for name in ("codesentry_files_analyzed_total", "codesentry_cache_events_total",
                 "codesentry_findings_total", "codesentry_analyzer_errors_total"):
        assert f"# TYPE {name} counter" in body


def test_an_unwritable_metrics_path_is_a_typed_error(tree, tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    proc = run_cli("review", str(tree), "--quiet", "--stdout", "--format", "json",
                   "--metrics-out", str(blocker / "run.prom"))
    assert proc.returncode == 2
    assert "cannot write metrics" in proc.stderr


# -- diff mode, end to end --------------------------------------------------
def test_diff_mode_reports_only_the_new_defect(tmp_path):
    base, head = tmp_path / "base", tmp_path / "head"
    for directory in (base, head):
        directory.mkdir()
        (directory / "old.py").write_text(DIRTY, encoding="utf-8")
    (head / "new.py").write_text("def f(s):\n    return eval(s)\n", encoding="utf-8")
    out = tmp_path / "reports"
    proc = run_cli("diff", "--base", str(base), "--head", str(head),
                   "--out", str(out), "--quiet", "--format", "json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((out / "diff_review.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "diff"
    assert {f["file"] for f in payload["findings"]} == {"new.py"}
