"""Incremental analysis: a SQLite cache keyed on content and configuration.

Every run used to re-read, re-parse and re-analyze every file, which is fine for
a demo and wrong for a pre-commit hook on a large repository. A cached entry is
valid only while all four of these are unchanged:

    (path, sha256 of the file's bytes, sha256 of the effective config,
     analyzer version)

so editing a file, changing a threshold, disabling a rule or upgrading the tool
all invalidate exactly what they should and nothing else. Entries are stored as
JSON, never pickle: the cache file is a plain file on disk that a hostile repo
could replace, and unpickling it would be remote code execution.

Schema changes go through `_MIGRATIONS`, applied forward inside one transaction
per step and recorded in `schema_version`. Opening a database written by a newer
version is an error rather than a silent wrong answer.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass

from . import __version__
from .analyzers import AnalyzerConfig, Finding
from .duplication import CodeBlock
from .errors import CacheError
from .logging_setup import get_logger
from .metrics import FunctionMetrics, ModuleMetrics

log = get_logger("cache")

#: Bumped whenever a rule's behaviour changes within one release. Combined with
#: the package version it forms the analyzer half of the cache key, so both a
#: release upgrade and an in-place rule fix invalidate every stored entry.
RULE_REVISION = 4
ANALYZER_VERSION = f"{__version__}+r{RULE_REVISION}"

DEFAULT_CACHE_DIRNAME = ".codesentry-cache"
DEFAULT_CACHE_FILENAME = "cache.db"

_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, """
        CREATE TABLE file_analysis (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            path             TEXT    NOT NULL,
            content_sha      TEXT    NOT NULL,
            config_sha       TEXT    NOT NULL,
            analyzer_version TEXT    NOT NULL,
            findings         TEXT    NOT NULL,
            metrics          TEXT    NOT NULL,
            blocks           TEXT    NOT NULL,
            created_at       REAL    NOT NULL,
            CONSTRAINT file_analysis_unique
                UNIQUE (path, content_sha, config_sha, analyzer_version)
        );
        CREATE INDEX idx_file_analysis_path ON file_analysis (path);
        CREATE INDEX idx_file_analysis_created ON file_analysis (created_at);
     """),
    (2, """
        ALTER TABLE file_analysis ADD COLUMN hit_count INTEGER NOT NULL DEFAULT 0;
        CREATE INDEX idx_file_analysis_lookup
            ON file_analysis (path, content_sha, config_sha, analyzer_version);
     """),
)

SCHEMA_VERSION = _MIGRATIONS[-1][0]

CachedEntry = tuple[list[Finding], ModuleMetrics, list[CodeBlock]]


def sha256_text(text: str) -> str:
    """Hex sha256 of a string's UTF-8 bytes."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def config_fingerprint(config: AnalyzerConfig) -> str:
    """Stable hash of every knob that can change a file's findings."""
    payload = {
        "max_complexity": config.max_complexity,
        "max_nesting": config.max_nesting,
        "max_fn_lines": config.max_fn_lines,
        "max_params": config.max_params,
        "max_line_len": config.max_line_len,
        "max_imports": config.max_imports,
        "skip_rules": sorted(config.skip_rules),
    }
    return sha256_text(json.dumps(payload, sort_keys=True))


def default_cache_path(root: str) -> str:
    """`<root>/.codesentry-cache/cache.db`, or `$CODESENTRY_CACHE` when set."""
    override = os.environ.get("CODESENTRY_CACHE", "").strip()
    if override:
        return os.path.abspath(override)
    return os.path.join(os.path.abspath(root), DEFAULT_CACHE_DIRNAME,
                        DEFAULT_CACHE_FILENAME)


def _finding_from_dict(data: dict, path: str) -> Finding:
    return Finding(file=path, line=int(data["line"]), rule=str(data["rule"]),
                   severity=str(data["severity"]), message=str(data["message"]),
                   suggestion=str(data["suggestion"]),
                   category=str(data["category"]), why=str(data.get("why", "")),
                   function=str(data.get("function", "")))


def _metrics_from_dict(data: dict, path: str) -> ModuleMetrics:
    functions = [
        FunctionMetrics(
            file=path, name=str(fn["name"]), line=int(fn["line"]),
            end_line=int(fn["end_line"]), complexity=int(fn["complexity"]),
            nesting=int(fn["nesting"]), length=int(fn["length"]),
            params=int(fn["params"]), has_docstring=bool(fn["has_docstring"]),
            is_public=bool(fn["is_public"]))
        for fn in data.get("functions", [])
    ]
    return ModuleMetrics(file=path, loc=int(data["loc"]), sloc=int(data["sloc"]),
                         functions=functions, classes=int(data.get("classes", 0)),
                         imports=tuple(data.get("imports", ())),
                         parse_ok=bool(data.get("parse_ok", True)))


def _block_to_dict(block: CodeBlock) -> dict:
    return {"name": block.name, "line": block.line, "end_line": block.end_line,
            "tokens": list(block.tokens)}


def _block_from_dict(data: dict, path: str) -> CodeBlock:
    return CodeBlock(file=path, name=str(data["name"]), line=int(data["line"]),
                     end_line=int(data["end_line"]),
                     tokens=tuple(str(t) for t in data["tokens"]))


@dataclass
class CacheStats:
    """What one run got out of the cache."""

    hits: int = 0
    misses: int = 0
    writes: int = 0

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {"hits": self.hits, "misses": self.misses, "writes": self.writes}


class AnalysisCache:
    """SQLite-backed store of per-file analysis results.

    Use as a context manager, or call `close()`. Reads are a single indexed
    lookup; writes are `INSERT OR REPLACE` inside a transaction. All SQL is
    parameterised - no identifier or value is ever interpolated into a statement.
    """

    def __init__(self, path: str, config: AnalyzerConfig,
                 analyzer_version: str = ANALYZER_VERSION):
        self.path = os.path.abspath(path)
        self.config_sha = config_fingerprint(config)
        self.analyzer_version = analyzer_version
        self.stats = CacheStats()
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        except OSError as exc:
            raise CacheError(f"cannot create the cache directory: {exc}",
                             path=self.path) from exc
        try:
            self._conn = sqlite3.connect(self.path)
            self._conn.row_factory = sqlite3.Row
            # The pragmas belong inside the try: sqlite3.connect() opens a file
            # lazily, so a path that is not a database only fails here, and it
            # has to surface as a typed CacheError like every other cache fault.
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error as exc:
            raise CacheError(f"cannot open cache: {exc}", path=self.path) from exc
        self._migrate()

    # -- schema ------------------------------------------------------------
    def _migrate(self) -> None:
        """Apply pending forward migrations, one transaction per step."""
        conn = self._conn
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version    INTEGER PRIMARY KEY,
                    applied_at REAL NOT NULL
                )""")
            conn.commit()
            row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = int(row["v"] or 0)
            if current > SCHEMA_VERSION:
                raise CacheError(
                    "cache was written by a newer codesentry; delete it or pass "
                    "--clear-cache", path=self.path, found=current,
                    supported=SCHEMA_VERSION)
            for version, script in _MIGRATIONS:
                if version <= current:
                    continue
                conn.executescript(script)
                conn.execute("INSERT INTO schema_version (version, applied_at) "
                             "VALUES (?, ?)", (version, time.time()))
                conn.commit()
                log.debug("applied cache migration", extra={"version": version})
        except sqlite3.DatabaseError as exc:
            conn.rollback()
            raise CacheError(f"cache schema is unusable: {exc}",
                             path=self.path) from exc

    # -- reads / writes ----------------------------------------------------
    def get(self, rel: str, source: str) -> tuple[list[Finding], ModuleMetrics] | None:
        """Cached findings and metrics for `rel`, or None on any invalidation."""
        entry = self.get_full(rel, source)
        if entry is None:
            return None
        findings, metrics, _blocks = entry
        return findings, metrics

    def get_full(self, rel: str, source: str) -> CachedEntry | None:
        """Cached findings, metrics and clone-detection blocks for `rel`."""
        try:
            row = self._conn.execute(
                "SELECT id, findings, metrics, blocks FROM file_analysis "
                "WHERE path = ? AND content_sha = ? AND config_sha = ? "
                "AND analyzer_version = ?",
                (rel, sha256_text(source), self.config_sha, self.analyzer_version),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise CacheError(f"cache read failed: {exc}", path=self.path) from exc
        if row is None:
            self.stats.misses += 1
            return None
        try:
            findings = [_finding_from_dict(d, rel) for d in json.loads(row["findings"])]
            metrics = _metrics_from_dict(json.loads(row["metrics"]), rel)
            blocks = [_block_from_dict(d, rel) for d in json.loads(row["blocks"])]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            # A corrupt row is a miss, not a crash: drop it and re-analyze.
            log.warning("dropping corrupt cache row",
                        extra={"file": rel, "reason": type(exc).__name__})
            self._conn.execute("DELETE FROM file_analysis WHERE id = ?", (row["id"],))
            self._conn.commit()
            self.stats.misses += 1
            return None
        self._conn.execute(
            "UPDATE file_analysis SET hit_count = hit_count + 1 WHERE id = ?",
            (row["id"],))
        self._conn.commit()
        self.stats.hits += 1
        return findings, metrics, blocks

    def put(self, rel: str, source: str, findings: list[Finding],
            metrics: ModuleMetrics, blocks: list[CodeBlock] | None = None) -> None:
        """Store one file's result, replacing any entry with the same key."""
        payload = (
            rel, sha256_text(source), self.config_sha, self.analyzer_version,
            json.dumps([f.to_dict() for f in findings]),
            json.dumps(metrics.to_dict()),
            json.dumps([_block_to_dict(b) for b in (blocks or [])]),
            time.time(),
        )
        try:
            with self._conn:  # one transaction, rolled back on error
                self._conn.execute(
                    "INSERT OR REPLACE INTO file_analysis "
                    "(path, content_sha, config_sha, analyzer_version, findings, "
                    " metrics, blocks, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    payload)
        except sqlite3.DatabaseError as exc:
            raise CacheError(f"cache write failed: {exc}", path=self.path) from exc
        self.stats.writes += 1

    # -- maintenance -------------------------------------------------------
    def prune(self, keep_per_path: int = 3) -> int:
        """Drop all but the newest `keep_per_path` entries per file; returns deleted."""
        try:
            with self._conn:
                cur = self._conn.execute(
                    "DELETE FROM file_analysis WHERE id NOT IN ("
                    "  SELECT id FROM ("
                    "    SELECT id, ROW_NUMBER() OVER "
                    "      (PARTITION BY path ORDER BY created_at DESC) AS rn"
                    "    FROM file_analysis"
                    "  ) WHERE rn <= ?"
                    ")", (int(keep_per_path),))
                return cur.rowcount or 0
        except sqlite3.DatabaseError as exc:
            raise CacheError(f"cache prune failed: {exc}", path=self.path) from exc

    def summary(self) -> dict:
        """Row count, distinct files and schema version, for `codesentry cache`."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS rows, COUNT(DISTINCT path) AS files, "
            "COALESCE(SUM(hit_count), 0) AS hits FROM file_analysis").fetchone()
        version = self._conn.execute(
            "SELECT MAX(version) AS v FROM schema_version").fetchone()["v"]
        return {"path": self.path, "rows": row["rows"], "files": row["files"],
                "lifetime_hits": row["hits"], "schema_version": int(version or 0),
                "size_bytes": os.path.getsize(self.path)
                if os.path.exists(self.path) else 0}

    def close(self) -> None:
        """Close the connection."""
        # Closing twice is harmless and happens whenever a context manager
        # wraps a cache the caller also closed explicitly.
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()

    def __enter__(self) -> AnalysisCache:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def clear_cache(path: str) -> bool:
    """Delete the cache database and its WAL sidecars; True when something went."""
    removed = False
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
            removed = True
    return removed
