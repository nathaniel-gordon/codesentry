"""Counters, histograms and the two dump formats.

The point of these tests is that the numbers a run reports are the numbers it
measured. A metrics surface that silently drops observations is worse than none,
because it looks like the system is idle.
"""
from __future__ import annotations

import json

import pytest

from reviewer.telemetry import (
    CACHE_EVENTS,
    FILE_DURATION,
    FILES_ANALYZED,
    Registry,
    declare,
    write_metrics,
)


@pytest.fixture()
def registry():
    return Registry()


# -- counters ---------------------------------------------------------------
def test_counter_starts_at_zero(registry):
    assert registry.counter("c").get() == 0.0


def test_counter_adds_up(registry):
    registry.inc("c")
    registry.inc("c", 4)
    assert registry.counter("c").get() == 5.0


def test_labels_are_separate_series(registry):
    registry.inc("c", result="hit")
    registry.inc("c", result="miss")
    registry.inc("c", result="hit")
    counter = registry.counter("c")
    assert (counter.get(result="hit"), counter.get(result="miss")) == (2.0, 1.0)
    assert counter.total() == 3.0


def test_label_order_does_not_split_a_series(registry):
    registry.inc("c", a="1", b="2")
    registry.inc("c", b="2", a="1")
    assert registry.counter("c").get(a="1", b="2") == 2.0


def test_counter_refuses_to_decrease(registry):
    with pytest.raises(ValueError):
        registry.inc("c", -1)


def test_declaring_twice_returns_the_same_counter(registry):
    first = registry.counter("c", "why")
    assert registry.counter("c") is first
    assert first.help == "why"


# -- histograms -------------------------------------------------------------
def test_observation_lands_in_the_first_containing_bucket(registry):
    registry.observe("h", 3.0)
    hist = registry.histogram("h")
    # buckets are 1, 2.5, 5, ... so 3.0 belongs to the 5.0 bucket and every
    # cumulative bucket at or above it.
    cumulative = hist.cumulative()
    assert cumulative[:3] == [0, 0, 1]
    assert cumulative[-1] == 1


def test_cumulative_counts_never_decrease(registry):
    for value in (0.5, 3.0, 40.0, 900.0, 90000.0):
        registry.observe("h", value)
    cumulative = registry.histogram("h").cumulative()
    assert cumulative == sorted(cumulative)


def test_sum_and_count_track_every_observation(registry):
    for value in (1.0, 2.0, 3.0):
        registry.observe("h", value)
    hist = registry.histogram("h")
    assert hist.count() == 3
    assert hist.sum() == pytest.approx(6.0)


def test_an_observation_past_the_last_bucket_still_counts(registry):
    registry.observe("h", 10_000_000.0)
    hist = registry.histogram("h")
    assert hist.count() == 1
    assert hist.cumulative()[-1] == 0  # no bucket contains it
    assert hist.sum() == pytest.approx(10_000_000.0)


def test_quantile_of_an_empty_histogram_is_zero(registry):
    assert registry.histogram("h").quantile(0.95) == 0.0


def test_quantile_returns_a_bucket_bound(registry):
    for _ in range(99):
        registry.observe("h", 2.0)
    registry.observe("h", 9000.0)
    hist = registry.histogram("h")
    assert hist.quantile(0.5) == 2.5
    assert hist.quantile(0.99) == 2.5
    assert hist.quantile(1.0) == 10000.0


def test_timed_records_the_block(registry):
    with registry.timed("h", phase="x"):
        pass
    assert registry.histogram("h").count(phase="x") == 1


def test_timed_records_even_when_the_block_raises(registry):
    with pytest.raises(RuntimeError), registry.timed("h", phase="x"):
        raise RuntimeError("boom")
    assert registry.histogram("h").count(phase="x") == 1


# -- rendering --------------------------------------------------------------
def test_prometheus_output_declares_help_and_type(registry):
    registry.counter("codesentry_x_total", "how many x")
    registry.inc("codesentry_x_total")
    text = registry.render_prometheus()
    assert "# HELP codesentry_x_total how many x" in text
    assert "# TYPE codesentry_x_total counter" in text


def test_prometheus_histogram_has_an_inf_bucket_equal_to_the_count(registry):
    for value in (1.0, 5000.0, 10_000_000.0):
        registry.observe("h", value, phase="p")
    lines = registry.render_prometheus().splitlines()
    inf = [ln for ln in lines if 'le="+Inf"' in ln]
    count = [ln for ln in lines if ln.startswith("h_count")]
    assert inf and count
    assert inf[0].rsplit(" ", 1)[1] == count[0].rsplit(" ", 1)[1] == "3"


def test_label_values_are_escaped(registry):
    registry.inc("c", path='a"b\\c')
    assert 'path="a\\"b\\\\c"' in registry.render_prometheus()


def test_declared_series_appear_even_when_nothing_happened(registry):
    declare(registry)
    text = registry.render_prometheus()
    for name in (FILES_ANALYZED, CACHE_EVENTS, FILE_DURATION):
        assert f"# TYPE {name} " in text
    assert f"{FILES_ANALYZED} 0" in text


def test_reset_drops_every_series(registry):
    registry.inc("c")
    registry.observe("h", 1.0)
    registry.reset()
    assert registry.counters == {} and registry.histograms == {}


def test_to_dict_is_json_serialisable(registry):
    registry.inc("c", result="hit")
    registry.observe("h", 12.0, phase="p")
    payload = json.loads(json.dumps(registry.to_dict()))
    assert payload["counters"]["c"]["total"] == 1.0
    series = payload["histograms"]["h"]["series"][0]
    assert series["count"] == 1 and series["labels"] == {"phase": "p"}


# -- the dump ---------------------------------------------------------------
def test_dump_writes_prometheus_text(tmp_path, registry):
    registry.inc("c")
    path = write_metrics(str(tmp_path / "m.prom"), registry)
    with open(path, encoding="utf-8") as handle:
        assert "# TYPE c counter" in handle.read()


def test_dump_writes_json_when_the_path_says_so(tmp_path, registry):
    registry.inc("c")
    path = write_metrics(str(tmp_path / "m.json"), registry)
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle)["counters"]["c"]["total"] == 1.0


def test_dump_creates_the_parent_directory(tmp_path, registry):
    path = write_metrics(str(tmp_path / "deep" / "er" / "m.prom"), registry)
    with open(path, encoding="utf-8") as handle:
        assert handle.read()
