"""Runtime counters and latency histograms for one review process.

This is the *operational* view of a run - how many files were analyzed, how many
came from the cache, how long each phase took. It is deliberately separate from
`metrics.py`, which measures the code being reviewed rather than the tool doing
the reviewing.

codesentry is a batch process, not a service: it starts, analyzes a tree and
exits. A Prometheus scrape endpoint would have nothing to scrape by the time the
scraper arrived, so the surface is a dump instead - `--metrics-out PATH` writes
the registry in Prometheus text exposition format (or JSON, when the path ends
in `.json`) as the last thing the run does. A textfile collector or a CI artifact
step can pick that up; see docs/adr/0004-metrics-as-a-dump-not-an-endpoint.md.

Everything is process-local and in-memory. There is no aggregation across runs,
no persistence, and no background thread.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

#: Bucket upper bounds in milliseconds. Chosen for what this tool actually does:
#: a single small file parses in single-digit ms, a whole repository takes
#: seconds, and anything past a minute is a runaway that only needs one bucket.
DEFAULT_BUCKETS_MS: tuple[float, ...] = (
    1.0, 2.5, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0,
    1000.0, 2500.0, 5000.0, 10000.0, 30000.0, 60000.0,
)

Labels = tuple[tuple[str, str], ...]


def _labels(pairs: dict[str, str] | None) -> Labels:
    """Normalise a label mapping into a hashable, order-stable key."""
    if not pairs:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in pairs.items()))


def _render_labels(labels: Labels, extra: str = "") -> str:
    """Render label pairs in Prometheus text format, escaping the value."""
    parts = [f'{k}="{_escape(v)}"' for k, v in labels]
    if extra:
        parts.append(extra)
    return "{" + ",".join(parts) + "}" if parts else ""


def _escape(value: str) -> str:
    """Escape a label value per the Prometheus exposition format."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@dataclass
class Counter:
    """A monotonically increasing count, one series per label set."""

    name: str
    help: str
    values: dict[Labels, float] = field(default_factory=dict)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        """Add `amount` (must not be negative) to the series for these labels."""
        if amount < 0:
            raise ValueError("counters cannot decrease")
        key = _labels(labels)
        self.values[key] = self.values.get(key, 0.0) + amount

    def get(self, **labels: str) -> float:
        """Current value of one series; 0.0 when it has never been touched."""
        return self.values.get(_labels(labels), 0.0)

    def total(self) -> float:
        """Sum across every label combination."""
        return sum(self.values.values())


@dataclass
class Histogram:
    """Cumulative latency histogram in milliseconds, plus sum and count."""

    name: str
    help: str
    buckets: tuple[float, ...] = DEFAULT_BUCKETS_MS
    counts: dict[Labels, list[int]] = field(default_factory=dict)
    sums: dict[Labels, float] = field(default_factory=dict)
    totals: dict[Labels, int] = field(default_factory=dict)

    def observe(self, millis: float, **labels: str) -> None:
        """Record one observation into the first bucket that contains it."""
        key = _labels(labels)
        counts = self.counts.setdefault(key, [0] * len(self.buckets))
        for index, bound in enumerate(self.buckets):
            if millis <= bound:
                counts[index] += 1
                break
        self.sums[key] = self.sums.get(key, 0.0) + millis
        self.totals[key] = self.totals.get(key, 0) + 1

    def count(self, **labels: str) -> int:
        """How many observations landed on one label set."""
        return self.totals.get(_labels(labels), 0)

    def sum(self, **labels: str) -> float:
        """Total milliseconds observed for one label set."""
        return self.sums.get(_labels(labels), 0.0)

    def cumulative(self, **labels: str) -> list[int]:
        """Bucket counts as Prometheus wants them: cumulative, low to high."""
        counts = self.counts.get(_labels(labels), [0] * len(self.buckets))
        running = 0
        out = []
        for value in counts:
            running += value
            out.append(running)
        return out

    def quantile(self, q: float, **labels: str) -> float:
        """Upper bound of the bucket holding quantile `q`.

        This is a bucket boundary, not an interpolated percentile: with 15
        buckets it is accurate to the bucket, which is all a histogram can
        honestly give. Returns 0.0 when nothing has been observed.
        """
        key = _labels(labels)
        total = self.totals.get(key, 0)
        if total == 0:
            return 0.0
        target = q * total
        for bound, running in zip(self.buckets, self.cumulative(**dict(key))):
            if running >= target:
                return bound
        return self.buckets[-1]


class Registry:
    """The metrics a single process has collected. Thread-safe, in-memory."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[str, Counter] = {}
        self.histograms: dict[str, Histogram] = {}
        self.started_at = time.time()

    # -- declaration -------------------------------------------------------
    def counter(self, name: str, help: str = "") -> Counter:
        """Get or create a counter. Repeat calls return the same object."""
        with self._lock:
            existing = self.counters.get(name)
            if existing is None:
                existing = Counter(name, help)
                self.counters[name] = existing
            elif help and not existing.help:
                existing.help = help
            return existing

    def histogram(self, name: str, help: str = "",
                  buckets: tuple[float, ...] = DEFAULT_BUCKETS_MS) -> Histogram:
        """Get or create a latency histogram. Repeat calls return the same object."""
        with self._lock:
            existing = self.histograms.get(name)
            if existing is None:
                existing = Histogram(name, help, buckets)
                self.histograms[name] = existing
            elif help and not existing.help:
                existing.help = help
            return existing

    # -- recording ---------------------------------------------------------
    def inc(self, name: str, amount: float = 1.0, **labels: str) -> None:
        """Increment a counter, creating it if this is its first use."""
        self.counter(name).inc(amount, **labels)

    def observe(self, name: str, millis: float, **labels: str) -> None:
        """Record a latency observation in milliseconds."""
        self.histogram(name).observe(millis, **labels)

    @contextmanager
    def timed(self, name: str, **labels: str) -> Iterator[None]:
        """Time the wrapped block and observe it, even if it raises.

        The observation happens in a `finally`, because a phase that blew up
        still took time and hiding that would make the slow path invisible.
        """
        started = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, (time.perf_counter() - started) * 1000.0, **labels)

    def reset(self) -> None:
        """Drop every series. Used by tests and between runs in one process."""
        with self._lock:
            self.counters.clear()
            self.histograms.clear()
            self.started_at = time.time()

    # -- output ------------------------------------------------------------
    def to_dict(self) -> dict:
        """JSON-serialisable snapshot of every series."""
        return {
            "uptime_s": round(time.time() - self.started_at, 3),
            "counters": {
                name: {
                    "help": counter.help,
                    "total": counter.total(),
                    "series": [{"labels": dict(labels), "value": value}
                               for labels, value in sorted(counter.values.items())],
                }
                for name, counter in sorted(self.counters.items())
            },
            "histograms": {
                name: {
                    "help": hist.help,
                    "buckets_ms": list(hist.buckets),
                    "series": [
                        {
                            "labels": dict(labels),
                            "count": hist.totals.get(labels, 0),
                            "sum_ms": round(hist.sums.get(labels, 0.0), 3),
                            "cumulative": hist.cumulative(**dict(labels)),
                            "p50_ms": hist.quantile(0.5, **dict(labels)),
                            "p95_ms": hist.quantile(0.95, **dict(labels)),
                        }
                        for labels in sorted(hist.totals)
                    ],
                }
                for name, hist in sorted(self.histograms.items())
            },
        }

    def render_prometheus(self) -> str:
        """Render every series in the Prometheus text exposition format."""
        lines: list[str] = []
        for name, counter in sorted(self.counters.items()):
            if counter.help:
                lines.append(f"# HELP {name} {counter.help}")
            lines.append(f"# TYPE {name} counter")
            if not counter.values:
                lines.append(f"{name} 0")
            for labels, value in sorted(counter.values.items()):
                lines.append(f"{name}{_render_labels(labels)} {value:g}")
        for name, hist in sorted(self.histograms.items()):
            if hist.help:
                lines.append(f"# HELP {name} {hist.help}")
            lines.append(f"# TYPE {name} histogram")
            for labels in sorted(hist.totals):
                cumulative = hist.cumulative(**dict(labels))
                for bound, running in zip(hist.buckets, cumulative):
                    suffix = _render_labels(labels, f'le="{bound:g}"')
                    lines.append(f"{name}_bucket{suffix} {running}")
                total = hist.totals[labels]
                inf = _render_labels(labels, 'le="+Inf"')
                lines.append(f"{name}_bucket{inf} {total}")
                lines.append(f"{name}_sum{_render_labels(labels)} "
                             f"{hist.sums.get(labels, 0.0):.3f}")
                lines.append(f"{name}_count{_render_labels(labels)} {total}")
        return "\n".join(lines) + "\n"


#: The registry the tool records into. One process, one review, one registry.
REGISTRY = Registry()

# Names are declared up front so `--metrics-out` on a run that analyzed nothing
# still emits the series rather than an empty file a dashboard cannot key on.
FILES_ANALYZED = "codesentry_files_analyzed_total"
CACHE_EVENTS = "codesentry_cache_events_total"
FINDINGS = "codesentry_findings_total"
ANALYZER_ERRORS = "codesentry_analyzer_errors_total"
SUPPRESSED = "codesentry_suppressed_findings_total"
FILE_DURATION = "codesentry_file_analysis_duration_ms"
PHASE_DURATION = "codesentry_phase_duration_ms"
RUN_DURATION = "codesentry_run_duration_ms"

_DECLARATIONS: tuple[tuple[str, str], ...] = (
    (FILES_ANALYZED, "Python files analyzed, labelled by cache outcome."),
    (CACHE_EVENTS, "Incremental cache lookups, labelled by result."),
    (FINDINGS, "Findings recorded, labelled by severity."),
    (ANALYZER_ERRORS, "Files an analyzer pass failed on. Any value here means exit 3."),
    (SUPPRESSED, "Findings hidden, labelled by the mechanism that hid them."),
)

_HISTOGRAM_DECLARATIONS: tuple[tuple[str, str], ...] = (
    (FILE_DURATION, "Wall-clock time to analyze one file, in milliseconds."),
    (PHASE_DURATION, "Wall-clock time per review phase, in milliseconds."),
    (RUN_DURATION, "Wall-clock time for a whole review, in milliseconds."),
)


def declare(registry: Registry | None = None) -> Registry:
    """Create every series this tool emits, so a quiet run still exposes them."""
    reg = registry or REGISTRY
    for name, description in _DECLARATIONS:
        reg.counter(name, description)
    for name, description in _HISTOGRAM_DECLARATIONS:
        reg.histogram(name, description)
    return reg


def write_metrics(path: str, registry: Registry | None = None) -> str:
    """Dump the registry to `path`; JSON when it ends in `.json`, else Prometheus.

    Returns the absolute path written. Raises OSError to the caller, which turns
    it into a typed InputError - a metrics dump that silently does nothing is
    worse than one that fails loudly.
    """
    reg = registry or REGISTRY
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    body = (json.dumps(reg.to_dict(), indent=2) + "\n"
            if target.endswith(".json") else reg.render_prometheus())
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(body)
    return target
