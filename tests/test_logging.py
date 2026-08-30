"""Structured logging: the JSON shape, the correlation id, and level control.

A log line is only useful in CI if a collector can key on it, so the JSON
format is a contract: one object per line, a run id on every record, and
structured extras as real fields rather than interpolated into the message.
Redaction is tested next door in test_security_regressions.py.
"""
from __future__ import annotations

import io
import json
import logging

import pytest

from reviewer.logging_setup import configure_logging, current_run_id, get_logger


def _log(level: str = "debug", fmt: str = "json", *, emit=None) -> str:
    stream = io.StringIO()
    configure_logging(level, fmt, stream=stream)
    (emit or (lambda log: log.warning("event")))(get_logger("t"))
    logging.getLogger("codesentry").handlers[0].flush()
    return stream.getvalue()


def test_json_records_are_one_object_per_line():
    out = _log(emit=lambda log: [log.warning("first"), log.warning("second")])
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 2
    assert [json.loads(ln)["event"] for ln in lines] == ["first", "second"]


def test_a_json_record_carries_the_expected_fields():
    payload = json.loads(_log())
    assert set(payload) >= {"ts", "level", "run_id", "logger", "event"}
    assert payload["level"] == "warning"
    assert payload["logger"] == "codesentry.t"


def test_extras_are_fields_not_interpolated_text():
    payload = json.loads(_log(emit=lambda log: log.info(
        "review finished", extra={"files": 12, "elapsed_ms": 4.5})))
    assert payload["files"] == 12 and payload["elapsed_ms"] == 4.5
    assert payload["event"] == "review finished"


def test_every_record_in_one_run_shares_the_id():
    out = _log(emit=lambda log: [log.warning("a"), log.warning("b")])
    ids = {json.loads(ln)["run_id"] for ln in out.splitlines() if ln.strip()}
    assert len(ids) == 1
    assert ids == {current_run_id()}


def test_a_new_run_gets_a_new_id():
    first = configure_logging("warning", "json", stream=io.StringIO())
    second = configure_logging("warning", "json", stream=io.StringIO())
    assert first != second and len(first) == len(second) == 12


def test_the_level_filters_records():
    assert _log(level="error", emit=lambda log: log.info("quiet")) == ""
    assert _log(level="info", emit=lambda log: log.info("loud")) != ""


def test_an_exception_is_reduced_to_its_last_line():
    def emit(log):
        try:
            raise ValueError("the reason")
        except ValueError:
            log.error("failed", exc_info=True)

    payload = json.loads(_log(emit=emit))
    assert payload["error"] == "ValueError: the reason"
    assert "Traceback" not in payload["error"]


def test_text_format_is_a_single_line_with_the_id():
    out = _log(fmt="text", emit=lambda log: log.warning("event", extra={"files": 3}))
    assert out.count("\n") == 1
    assert f"[{current_run_id()}]" in out
    assert out.rstrip().endswith("files=3")


def test_configure_logging_replaces_its_own_handler():
    for _ in range(3):
        configure_logging("warning", "json", stream=io.StringIO())
    assert len(logging.getLogger("codesentry").handlers) == 1


@pytest.mark.parametrize("value,expected", [("json", True), ("text", False)])
def test_the_environment_overrides_the_argument(monkeypatch, value, expected):
    monkeypatch.setenv("CODESENTRY_LOG_FORMAT", value)
    stream = io.StringIO()
    configure_logging("warning", "text", stream=stream)
    get_logger("t").warning("event")
    is_json = stream.getvalue().lstrip().startswith("{")
    assert is_json is expected


def test_the_environment_overrides_the_level(monkeypatch):
    monkeypatch.setenv("CODESENTRY_LOG_LEVEL", "debug")
    stream = io.StringIO()
    configure_logging("error", "json", stream=stream)
    get_logger("t").debug("chatty")
    assert "chatty" in stream.getvalue()


def test_records_do_not_propagate_to_the_root_logger(capsys):
    configure_logging("debug", "json", stream=io.StringIO())
    get_logger("t").error("event")
    assert capsys.readouterr().err == ""
