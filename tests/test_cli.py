"""The exit-code contract, which is the only thing CI can act on.

0 clean, 1 a gate failed, 2 the invocation was wrong, 3 the tool itself failed.
The last one matters most: a linter that exits 0 after crashing on a file is
worse than no linter, so an injected analyzer failure has to reach the exit
code, the JSON and the SARIF.
"""
from __future__ import annotations

import json

import pytest

from reviewer import __main__ as cli
from reviewer.errors import EXIT_GATE_FAILED, EXIT_INTERNAL, EXIT_OK, EXIT_USAGE

CLEAN = '"""Module."""\n\n\ndef add(a, b):\n    """Add two numbers."""\n    return a + b\n'
DIRTY = '"""Module."""\n\n\ndef run(text):\n    """Run text."""\n    return eval(text)\n'


@pytest.fixture
def project(tmp_path):
    """A tiny tree with one clean and one defective module."""
    (tmp_path / "clean.py").write_text(CLEAN, encoding="utf-8")
    (tmp_path / "dirty.py").write_text(DIRTY, encoding="utf-8")
    return tmp_path


def run(*argv):
    """Invoke the CLI exactly as a shell would."""
    return cli.main(list(argv))


def test_clean_tree_exits_zero(project, tmp_path):
    out = tmp_path / "reports"
    assert run("review", str(project / "clean.py"), "--out", str(out),
               "--no-cache", "--quiet") == EXIT_OK


def test_severity_gate_fails_on_critical(project, tmp_path):
    out = tmp_path / "reports"
    assert run("review", str(project / "dirty.py"), "--out", str(out), "--no-cache",
               "--quiet", "--fail-on-severity", "high") == EXIT_GATE_FAILED


def test_severity_gate_passes_when_nothing_reaches_the_floor(project, tmp_path):
    out = tmp_path / "reports"
    assert run("review", str(project / "clean.py"), "--out", str(out), "--no-cache",
               "--quiet", "--fail-on-severity", "critical") == EXIT_OK


def test_several_paths_are_accepted(project, tmp_path):
    """pre-commit appends every staged file; one positional path used to exit 2."""
    out = tmp_path / "reports"
    assert run("review", str(project / "clean.py"), str(project / "dirty.py"),
               "--out", str(out), "--no-cache", "--quiet") == EXIT_OK


def test_missing_path_is_a_usage_error(tmp_path):
    assert run("review", str(tmp_path / "nope.py"), "--no-cache",
               "--quiet") == EXIT_USAGE


def test_unknown_rule_is_a_usage_error(project, tmp_path):
    assert run("review", str(project), "--ignore", "not-a-rule", "--no-cache",
               "--quiet", "--out", str(tmp_path / "r")) == EXIT_USAGE


def test_unknown_pack_is_a_usage_error(project, tmp_path):
    assert run("review", str(project), "--pack", "nonsense", "--no-cache",
               "--quiet", "--out", str(tmp_path / "r")) == EXIT_USAGE


def test_ignore_silences_a_rule(project, tmp_path):
    out = tmp_path / "reports"
    run("review", str(project / "dirty.py"), "--out", str(out), "--no-cache",
        "--quiet", "--ignore", "eval-exec")
    payload = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert [f for f in payload["findings"] if f["rule"] == "eval-exec"] == []


def test_select_runs_only_the_named_rules(project, tmp_path):
    out = tmp_path / "reports"
    run("review", str(project / "dirty.py"), "--out", str(out), "--no-cache",
        "--quiet", "--select", "eval-exec")
    payload = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert {f["rule"] for f in payload["findings"]} == {"eval-exec"}


def test_sarif_is_written_when_requested(project, tmp_path):
    out = tmp_path / "reports"
    run("review", str(project / "dirty.py"), "--out", str(out), "--no-cache",
        "--quiet", "--format", "sarif")
    log = json.loads((out / "review.sarif").read_text(encoding="utf-8"))
    assert log["version"] == "2.1.0"
    assert log["runs"][0]["results"]


def test_analyzer_failure_exits_three(project, tmp_path, monkeypatch):
    """Injected analyzer bug: the run must not report a clean tree."""
    def explode(*_args, **_kwargs):
        raise RuntimeError("simulated analyzer bug")

    monkeypatch.setattr("reviewer.review.analyze_source", explode)
    out = tmp_path / "reports"
    code = run("review", str(project), "--out", str(out), "--no-cache", "--quiet")
    assert code == EXIT_INTERNAL
    payload = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["errors"]


def test_analyzer_failure_marks_sarif_unsuccessful(project, tmp_path, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("simulated analyzer bug")

    monkeypatch.setattr("reviewer.review.analyze_source", explode)
    out = tmp_path / "reports"
    run("review", str(project), "--out", str(out), "--no-cache", "--quiet",
        "--format", "sarif")
    log = json.loads((out / "review.sarif").read_text(encoding="utf-8"))
    assert log["runs"][0]["invocations"][0]["executionSuccessful"] is False


def test_rules_command_lists_every_rule(capsys):
    assert run("rules", "--json") == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["rules"]) == 30
    assert set(payload["packs"]) == {"security", "correctness", "complexity",
                                     "maintainability"}


def test_stdout_mode_writes_no_files(project, tmp_path, capsys):
    assert run("review", str(project / "clean.py"), "--stdout", "--format", "json",
               "--no-cache", "--out", str(tmp_path / "unused")) == EXIT_OK
    json.loads(capsys.readouterr().out)
    assert not (tmp_path / "unused").exists()


def test_baseline_then_review_suppresses_everything(project, tmp_path):
    baseline = tmp_path / "baseline.json"
    assert run("baseline", str(project), "--output", str(baseline)) == EXIT_OK
    out = tmp_path / "reports"
    assert run("review", str(project), "--out", str(out), "--no-cache", "--quiet",
               "--baseline", str(baseline), "--fail-on-severity",
               "critical") == EXIT_OK
    payload = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert payload["findings"] == []
    assert payload["summary"]["suppressed"]["by_baseline"] > 0


# -- the remaining subcommands --------------------------------------------
def test_demo_runs_clean(tmp_path):
    assert run("demo", "--out", str(tmp_path)) == EXIT_OK
    assert (tmp_path / "review.sarif").exists()
    assert (tmp_path / "evaluation.json").exists()


def test_eval_publishes_per_rule_scores(tmp_path):
    assert run("eval", "--out", str(tmp_path)) == EXIT_OK
    payload = json.loads((tmp_path / "evaluation.json").read_text(encoding="utf-8"))
    assert payload["per_rule"]
    assert all(row["fn"] == 0 for row in payload["per_rule"])


def test_metrics_command_runs(project, capsys):
    assert run("metrics", str(project), "--top", "3") == EXIT_OK
    assert "health score" in capsys.readouterr().out


def test_cache_command_reports_and_clears(project, tmp_path, capsys):
    db = tmp_path / "cache.db"
    run("review", str(project), "--out", str(tmp_path / "r"), "--quiet",
        "--cache-path", str(db))
    assert run("cache", str(project), "--cache-path", str(db)) == EXIT_OK
    assert "schema_version" in capsys.readouterr().out
    assert run("cache", str(project), "--cache-path", str(db), "--clear") == EXIT_OK
    assert not db.exists()


def test_patch_command_limits_findings_to_the_diff(project, tmp_path):
    patch = tmp_path / "change.diff"
    patch.write_text("--- a/dirty.py\n+++ b/dirty.py\n@@ -5,1 +5,1 @@\n"
                     "+    return eval(text)\n", encoding="utf-8")
    out = tmp_path / "reports"
    assert run("patch", str(project), "--diff", str(patch), "--out", str(out),
               "--no-cache", "--quiet") == EXIT_OK
    payload = json.loads((out / "patch_review.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "diff"
    assert all(f["file"] == "dirty.py" for f in payload["findings"])


def test_diff_command_gates_on_severity(tmp_path):
    base = tmp_path / "base"
    head = tmp_path / "head"
    base.mkdir()
    head.mkdir()
    (base / "m.py").write_text(CLEAN, encoding="utf-8")
    (head / "m.py").write_text(CLEAN + "\n\ndef run(t):\n    \"\"\"R.\"\"\"\n"
                               "    return eval(t)\n", encoding="utf-8")
    out = tmp_path / "reports"
    assert run("diff", "--base", str(base), "--head", str(head), "--out", str(out),
               "--no-cache", "--quiet", "--fail-on-severity",
               "critical") == EXIT_GATE_FAILED


def test_diff_command_rejects_a_missing_directory(tmp_path):
    assert run("diff", "--base", str(tmp_path / "nope"), "--head", str(tmp_path),
               "--no-cache", "--quiet") == EXIT_USAGE


def test_report_records_the_settings_it_ran_with(project, tmp_path):
    """A report has to be reproducible from itself, not from today's config."""
    out = tmp_path / "reports"
    run("review", str(project), "--out", str(out), "--no-cache", "--quiet",
        "--ignore", "eval-exec", "--no-config")
    payload = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert payload["run_id"]
    assert "eval-exec" in payload["settings"]["skipped_rules"]


def test_log_flags_are_accepted_after_the_subcommand(project, tmp_path):
    assert run("review", str(project / "clean.py"), "--out", str(tmp_path / "r"),
               "--no-cache", "--quiet", "--log-level", "error") == EXIT_OK


# -- where reports land when --out is not given ----------------------------
def test_default_report_dir_follows_the_working_directory(project, tmp_path,
                                                          monkeypatch):
    """Anchored on the cwd, not on the package.

    An installed codesentry lives in site-packages, and the previous anchor put
    `output/` there: wrong on any machine and unwritable for the container's
    non-root user.
    """
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    assert run("review", str(project / "clean.py"), "--no-cache", "--quiet") == EXIT_OK
    assert (workdir / "output" / "review.json").is_file()


def test_unwritable_report_dir_is_a_typed_error_not_a_traceback(project, tmp_path,
                                                                monkeypatch):
    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(cli.os, "makedirs", refuse)
    monkeypatch.chdir(tmp_path)
    assert run("review", str(project / "clean.py"), "--no-cache", "--quiet") == EXIT_USAGE

