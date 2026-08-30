"""Pins the numbers the README publishes.

The `_resource_is_managed` crash shipped because nothing asserted on the demo's
recall: the run exited 0, printed a lower number than the run before, and no
test noticed. These tests fail if detection regresses or if a rule starts firing
on the benign corpus, which is the pair of properties the README quotes.
"""
from __future__ import annotations

import pytest

from reviewer.analyzers import RULES, AnalyzerConfig
from reviewer.datagen import build_manifest, write_demo_repo
from reviewer.evaluation import evaluate, rule_scores
from reviewer.pipeline import review_repo


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """Generate the corpus once and review it once for the whole module."""
    root = tmp_path_factory.mktemp("corpus") / "base"
    manifest = write_demo_repo(str(root))
    result, _ = review_repo(str(root), config=AnalyzerConfig())
    return manifest, result


def test_every_rule_has_ground_truth():
    """A rule with no plant has unmeasured recall, not perfect recall."""
    planted = {p.rule for p in build_manifest("x").plants}
    assert set(RULES) - planted == set()


def test_no_file_fails_to_analyze(corpus):
    _manifest, result = corpus
    assert result.errors == [], [e.to_dict() for e in result.errors]
    assert result.ok


def test_all_planted_defects_are_reported(corpus):
    manifest, result = corpus
    report = evaluate(result.findings, manifest)
    assert report.missed == [], [p.to_dict() for p in report.missed]
    assert report.recall == 1.0


def test_no_finding_on_the_benign_corpus(corpus):
    """Every benign file is adversarial; a finding on one is a false positive."""
    manifest, result = corpus
    benign = set(manifest.clean_files)
    hits = [f.to_dict() for f in result.findings if f.file in benign]
    assert hits == []


def test_per_rule_scores_are_complete(corpus):
    manifest, result = corpus
    scores = {s.rule: s for s in rule_scores(result.findings, manifest)}
    assert set(scores) == set(RULES)
    for rule, score in scores.items():
        assert score.fn == 0, f"{rule} missed a planted defect"
        assert score.fp == 0, f"{rule} fired on the benign corpus"


def test_diff_mode_catches_the_introduced_defect(tmp_path):
    """The head revision plants one new defect; the gate exists to catch it."""
    from reviewer.pipeline import review_diff
    base = tmp_path / "base"
    head = tmp_path / "head"
    write_demo_repo(str(base))
    head_manifest = write_demo_repo(str(head), head=True)
    result, _ = review_diff(str(base), str(head), config=AnalyzerConfig())
    introduced = {p.key for p in head_manifest.plants if p.introduced}
    assert introduced, "the head revision should introduce at least one defect"
    assert introduced <= {f.key for f in result.findings}


def test_diff_mode_does_not_re_report_untouched_lines(tmp_path):
    from reviewer.pipeline import review_diff
    base = tmp_path / "base"
    head = tmp_path / "head"
    write_demo_repo(str(base))
    head_manifest = write_demo_repo(str(head), head=True)
    result, _ = review_diff(str(base), str(head), config=AnalyzerConfig())
    reported = {f.key for f in result.findings}
    touched = set(result.metrics)
    stale = [p.key for p in head_manifest.plants
             if not p.introduced and p.file in touched and p.key in reported]
    assert stale == []
