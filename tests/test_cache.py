"""Cache invalidation, which is where an incremental analyzer goes wrong.

A stale hit is worse than no cache: the tool reports yesterday's findings for
today's code and the run still exits 0. Each of the four key components gets its
own test, plus the failure modes - a corrupt row, and a database written by a
newer version of the tool.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from reviewer.analyzers import AnalyzerConfig, analyze_source
from reviewer.cache import (
    ANALYZER_VERSION,
    AnalysisCache,
    CacheError,
    clear_cache,
    config_fingerprint,
)
from reviewer.errors import EXIT_OK
from reviewer.metrics import module_metrics

SOURCE = '"""Module."""\n\n\ndef run(text):\n    """Run."""\n    return eval(text)\n'


def _store(cache, rel="a.py", source=SOURCE):
    findings = analyze_source(rel, source)
    metrics = module_metrics(rel, source, None)
    cache.put(rel, source, findings, metrics, [])
    return findings


@pytest.fixture
def cache(tmp_path):
    with AnalysisCache(str(tmp_path / "c.db"), AnalyzerConfig()) as handle:
        yield handle


def test_miss_then_hit(cache):
    assert cache.get("a.py", SOURCE) is None
    stored = _store(cache)
    hit = cache.get("a.py", SOURCE)
    assert hit is not None
    assert [f.key for f in hit[0]] == [f.key for f in stored]
    assert cache.stats.hits == 1 and cache.stats.misses == 1


def test_changed_content_invalidates(cache):
    _store(cache)
    assert cache.get("a.py", SOURCE + "# edited\n") is None


def test_changed_config_invalidates(tmp_path):
    path = str(tmp_path / "c.db")
    with AnalysisCache(path, AnalyzerConfig()) as first:
        _store(first)
    with AnalysisCache(path, AnalyzerConfig(max_complexity=3)) as second:
        assert second.get("a.py", SOURCE) is None


def test_disabling_a_rule_invalidates(tmp_path):
    path = str(tmp_path / "c.db")
    with AnalysisCache(path, AnalyzerConfig()) as first:
        _store(first)
    skipped = AnalyzerConfig(skip_rules=frozenset({"eval-exec"}))
    with AnalysisCache(path, skipped) as second:
        assert second.get("a.py", SOURCE) is None


def test_new_analyzer_version_invalidates(tmp_path):
    path = str(tmp_path / "c.db")
    with AnalysisCache(path, AnalyzerConfig()) as first:
        _store(first)
    with AnalysisCache(path, AnalyzerConfig(), analyzer_version="99") as second:
        assert second.get("a.py", SOURCE) is None


def test_config_fingerprint_ignores_key_order():
    a = AnalyzerConfig(skip_rules=frozenset({"eval-exec", "weak-hash"}))
    b = AnalyzerConfig(skip_rules=frozenset({"weak-hash", "eval-exec"}))
    assert config_fingerprint(a) == config_fingerprint(b)


def test_corrupt_row_is_a_miss_not_a_crash(cache):
    _store(cache)
    cache._conn.execute("UPDATE file_analysis SET findings = ?", ("{not json",))
    cache._conn.commit()
    assert cache.get("a.py", SOURCE) is None


def test_schema_from_a_newer_tool_is_refused(tmp_path):
    path = str(tmp_path / "c.db")
    with AnalysisCache(path, AnalyzerConfig()):
        pass
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (999, 0)")
    conn.commit()
    conn.close()
    with pytest.raises(CacheError):
        AnalysisCache(path, AnalyzerConfig())


def test_migrations_are_idempotent(tmp_path):
    path = str(tmp_path / "c.db")
    for _ in range(3):
        with AnalysisCache(path, AnalyzerConfig()) as handle:
            summary = handle.summary()
    assert summary["schema_version"] >= 2


def test_prune_keeps_the_newest_entries(cache):
    for i in range(5):
        _store(cache, source=SOURCE + f"# {i}\n")
    assert cache.prune(keep_per_path=2) == 3
    assert cache.summary()["rows"] == 2


def test_clear_removes_the_database(tmp_path):
    path = str(tmp_path / "c.db")
    with AnalysisCache(path, AnalyzerConfig()) as handle:
        _store(handle)
    assert clear_cache(path) is True
    assert clear_cache(path) is False


def test_warm_run_reuses_results_through_the_cli(tmp_path):
    from reviewer import __main__ as cli
    project = tmp_path / "src"
    project.mkdir()
    (project / "m.py").write_text(SOURCE, encoding="utf-8")
    out = tmp_path / "reports"
    db = tmp_path / "cache.db"
    args = ["review", str(project), "--out", str(out), "--quiet",
            "--cache-path", str(db)]
    assert cli.main(args) == EXIT_OK
    cold = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert cold["summary"]["cache"]["misses"] == 1
    assert cli.main(args) == EXIT_OK
    warm = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert warm["summary"]["cache"]["hits"] == 1
    assert [f["rule"] for f in warm["findings"]] == [f["rule"] for f in cold["findings"]]


def test_version_string_tracks_the_package():
    from reviewer import __version__
    assert ANALYZER_VERSION.startswith(__version__)
