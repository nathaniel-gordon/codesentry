"""SARIF output: valid enough for GitHub code scanning to accept and dedupe.

The parts that actually matter downstream are the ones tested here - the level
mapping, the rule index, the fingerprint's independence from line numbers, and
the invocation's success flag.
"""
from __future__ import annotations

from reviewer.analyzers import RULES, Finding, analyze_source
from reviewer.errors import AnalysisError
from reviewer.review import ReviewResult, ReviewSession
from reviewer.sarif import (FINGERPRINT_KEY, LEVEL_FOR_SEVERITY, fingerprint,
                            render_sarif)

SOURCE = '"""Module."""\n\n\ndef run(text):\n    """Run."""\n    return eval(text)\n'


def build(tmp_path, source=SOURCE, name="m.py"):
    """Review a one-file tree and return its ReviewResult."""
    (tmp_path / name).write_text(source, encoding="utf-8")
    session = ReviewSession(str(tmp_path))
    session.analyze_all()
    return session.finalize()


def test_envelope_is_sarif_210(tmp_path):
    log = render_sarif(build(tmp_path))
    assert log["version"] == "2.1.0"
    assert log["$schema"].endswith("sarif-2.1.0.json")
    assert len(log["runs"]) == 1


def test_driver_publishes_every_rule(tmp_path):
    driver = render_sarif(build(tmp_path))["runs"][0]["tool"]["driver"]
    assert {r["id"] for r in driver["rules"]} == set(RULES)
    for descriptor in driver["rules"]:
        assert descriptor["fullDescription"]["text"]
        assert descriptor["defaultConfiguration"]["level"] in {"error", "warning",
                                                               "note"}


def test_rule_index_points_at_the_right_descriptor(tmp_path):
    run = render_sarif(build(tmp_path))["runs"][0]
    rules = run["tool"]["driver"]["rules"]
    for result in run["results"]:
        assert rules[result["ruleIndex"]]["id"] == result["ruleId"]


def test_levels_follow_the_severity_map(tmp_path):
    run = render_sarif(build(tmp_path))["runs"][0]
    for result in run["results"]:
        expected = LEVEL_FOR_SEVERITY[result["properties"]["severity"]]
        assert result["level"] == expected


def test_locations_are_relative_and_one_based(tmp_path):
    run = render_sarif(build(tmp_path))["runs"][0]
    assert run["results"], "the sample source should produce a finding"
    for result in run["results"]:
        location = result["locations"][0]["physicalLocation"]
        assert location["artifactLocation"]["uri"] == "m.py"
        assert location["region"]["startLine"] >= 1


def test_fingerprint_survives_a_line_shift():
    """GitHub dedupes on the fingerprint, so an edit above must not reset it."""
    before = analyze_source("m.py", SOURCE)
    after = analyze_source("m.py", '"""Module."""\n# a new comment\n' + SOURCE[14:])
    assert before and after
    assert fingerprint(before[0]) == fingerprint(after[0])


def test_fingerprint_differs_between_rules():
    a = Finding("m.py", 1, "eval-exec", "critical", "msg", "fix", "security")
    b = Finding("m.py", 1, "os-system", "critical", "msg", "fix", "security")
    assert fingerprint(a) != fingerprint(b)


def test_every_result_carries_a_fingerprint(tmp_path):
    run = render_sarif(build(tmp_path))["runs"][0]
    for result in run["results"]:
        assert result["partialFingerprints"][FINGERPRINT_KEY]


def test_clean_run_is_marked_successful(tmp_path):
    result = build(tmp_path, '"""Module."""\n')
    invocation = render_sarif(result)["runs"][0]["invocations"][0]
    assert invocation["executionSuccessful"] is True
    assert invocation["toolExecutionNotifications"] == []


def test_analyzer_failure_is_reported_in_the_log():
    result = ReviewResult(root=".", findings=[], metrics={}, health=_health(),
                          churn=_churn(), duplicate_pairs=[])
    result.errors.append(AnalysisError("RuntimeError: boom", file="broken.py"))
    invocation = render_sarif(result)["runs"][0]["invocations"][0]
    assert invocation["executionSuccessful"] is False
    assert invocation["toolExecutionNotifications"][0]["message"]["text"]


def _health():
    from reviewer.review import HealthScore
    return HealthScore(score=100.0, grade="A", components={})


def _churn():
    from reviewer.churn import ChurnModel
    return ChurnModel(raw={}, source="none")
