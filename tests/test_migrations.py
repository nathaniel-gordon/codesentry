"""Schema migrations for the SQLite result cache.

test_cache.py covers what the cache is *for* - hits, misses and invalidation.
This file covers the database underneath it: that a store written by an older
build is carried forward without losing its rows, that a failed migration leaves
no half-applied version behind, and that the constraints and pragmas the cache
relies on are really in the file.
"""
from __future__ import annotations

import sqlite3

import pytest

from reviewer.analyzers import AnalyzerConfig, analyze_source
from reviewer.cache import _MIGRATIONS, SCHEMA_VERSION, AnalysisCache
from reviewer.errors import CacheError
from reviewer.metrics import module_metrics

SOURCE = "def f(x):\n    return eval(x)\n"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _build_at_version(path, version: int) -> None:
    """Create a database holding only the migrations up to `version`."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version ("
                 "version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
    for number, script in _MIGRATIONS:
        if number > version:
            break
        conn.executescript(script)
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, 0)",
                     (number,))
    conn.commit()
    conn.close()


def _store(cache: AnalysisCache, rel: str = "a.py", source: str = SOURCE) -> None:
    cache.put(rel, source, analyze_source(rel, source, AnalyzerConfig()),
              module_metrics(rel, source), [])


# -- forward migration ------------------------------------------------------
def test_a_v1_database_migrates_to_the_current_schema(tmp_path):
    path = str(tmp_path / "c.db")
    _build_at_version(path, 1)
    with AnalysisCache(path, AnalyzerConfig()) as cache:
        assert cache.summary()["schema_version"] == SCHEMA_VERSION


def test_migrating_keeps_the_rows_the_old_build_wrote(tmp_path):
    path = str(tmp_path / "c.db")
    _build_at_version(path, 1)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO file_analysis (path, content_sha, config_sha, "
        "analyzer_version, findings, metrics, blocks, created_at) "
        "VALUES ('legacy.py', 'sha', 'cfg', 'old', '[]', '{}', '[]', 0)")
    conn.commit()
    conn.close()
    with AnalysisCache(path, AnalyzerConfig()) as cache:
        summary = cache.summary()
    assert summary["rows"] == 1 and summary["files"] == 1


def test_migration_two_adds_the_hit_counter(tmp_path):
    path = str(tmp_path / "c.db")
    _build_at_version(path, 1)
    conn = sqlite3.connect(path)
    assert "hit_count" not in _columns(conn, "file_analysis")
    conn.close()
    with AnalysisCache(path, AnalyzerConfig()):
        pass
    conn = sqlite3.connect(path)
    assert "hit_count" in _columns(conn, "file_analysis")
    conn.close()


def test_every_applied_migration_is_recorded(tmp_path):
    path = str(tmp_path / "c.db")
    with AnalysisCache(path, AnalyzerConfig()):
        pass
    conn = sqlite3.connect(path)
    recorded = [row[0] for row in
                conn.execute("SELECT version FROM schema_version ORDER BY version")]
    conn.close()
    assert recorded == [version for version, _script in _MIGRATIONS]


def test_reopening_applies_nothing_new(tmp_path):
    path = str(tmp_path / "c.db")
    for _ in range(3):
        with AnalysisCache(path, AnalyzerConfig()):
            pass
    conn = sqlite3.connect(path)
    count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    conn.close()
    assert count == len(_MIGRATIONS)


def test_a_failing_migration_records_no_version(tmp_path, monkeypatch):
    """A broken step must not leave the database claiming it succeeded."""
    broken = (*_MIGRATIONS, (SCHEMA_VERSION + 1, "CREATE TABLE ;;;"))
    monkeypatch.setattr("reviewer.cache._MIGRATIONS", broken)
    path = str(tmp_path / "c.db")
    with pytest.raises(CacheError):
        AnalysisCache(path, AnalyzerConfig())
    conn = sqlite3.connect(path)
    highest = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    conn.close()
    assert highest == SCHEMA_VERSION


def test_a_file_that_is_not_a_database_is_a_typed_error(tmp_path):
    path = tmp_path / "c.db"
    path.write_bytes(b"this is not sqlite" * 100)
    with pytest.raises(CacheError):
        AnalysisCache(str(path), AnalyzerConfig())


def test_a_failed_open_closes_its_connection(tmp_path, monkeypatch):
    """When __init__ raises, the caller has nothing to close - we must.

    Regression: init used to raise CacheError with the sqlite connection
    still open, which surfaced as unclosed-database ResourceWarnings in
    whatever test the garbage collector happened to run under.
    """
    opened = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr("reviewer.cache.sqlite3.connect", tracking_connect)

    # pragma failure: the file exists but is not a database
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"this is not sqlite" * 100)
    with pytest.raises(CacheError):
        AnalysisCache(str(garbage), AnalyzerConfig())

    # migration refusal: schema written by a newer tool
    newer = str(tmp_path / "newer.db")
    with AnalysisCache(newer, AnalyzerConfig()):
        pass
    conn = real_connect(newer)
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (999, 0)")
    conn.commit()
    conn.close()
    with pytest.raises(CacheError):
        AnalysisCache(newer, AnalyzerConfig())

    for tracked in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            tracked.execute("SELECT 1")  # closed connections refuse queries


# -- the schema the cache relies on -----------------------------------------
def test_journal_mode_is_wal(tmp_path):
    path = str(tmp_path / "c.db")
    with AnalysisCache(path, AnalyzerConfig()) as cache:
        mode = cache._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_the_lookup_indexes_exist(tmp_path):
    path = str(tmp_path / "c.db")
    with AnalysisCache(path, AnalyzerConfig()) as cache:
        names = {row["name"] for row in cache._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND name LIKE 'idx_%'")}
    assert names == {"idx_file_analysis_path", "idx_file_analysis_created",
                     "idx_file_analysis_lookup"}


def test_the_cache_key_is_unique(tmp_path):
    path = str(tmp_path / "c.db")
    with AnalysisCache(path, AnalyzerConfig()) as cache:
        _store(cache)
        _store(cache)
        assert cache.summary()["rows"] == 1


def test_a_second_connection_can_read_while_the_first_is_open(tmp_path):
    """WAL is there so a pre-commit hook and an editor plugin do not deadlock."""
    path = str(tmp_path / "c.db")
    with AnalysisCache(path, AnalyzerConfig()) as writer:
        _store(writer)
        with AnalysisCache(path, AnalyzerConfig()) as reader:
            assert reader.get_full("a.py", SOURCE) is not None


def test_clearing_removes_the_wal_sidecars(tmp_path):
    from reviewer.cache import clear_cache
    path = str(tmp_path / "c.db")
    with AnalysisCache(path, AnalyzerConfig()) as cache:
        _store(cache)
    assert clear_cache(path) is True
    assert not list(tmp_path.glob("c.db*"))
