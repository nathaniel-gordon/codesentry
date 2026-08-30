"""Structured logging with a per-run correlation id.

A review is one unit of work that touches many files and (optionally) an LLM.
When something goes wrong in CI the only useful question is "what happened
during *that* run", so every record carries the same `run_id`. The id is held in
a ContextVar rather than passed around, because the agent loop, the cache and
the analyzers are all called from code that has no business threading an id
through its signatures.

Two formats: `text` for a terminal, `json` for a log collector. Nothing here
ever logs file *contents*, a secret value, or an API key - findings log the
rule id and location only.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar

RUN_ID: ContextVar[str] = ContextVar("codesentry_run_id", default="-")

#: Field names whose values are never written to a log record.
REDACTED_KEYS = frozenset({
    "api_key", "anthropic_api_key", "token", "secret", "password", "value",
    "source", "credential",
})
_REDACTED = "***"

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message", "asctime", "taskName"}


def new_run_id() -> str:
    """Start a new correlation id for this run and return it."""
    run_id = uuid.uuid4().hex[:12]
    RUN_ID.set(run_id)
    return run_id


def current_run_id() -> str:
    """The correlation id of the run in progress."""
    return RUN_ID.get()


def _extras(record: logging.LogRecord) -> dict[str, object]:
    """Structured fields attached via `logger.info(..., extra={...})`, redacted."""
    out: dict[str, object] = {}
    for key, value in record.__dict__.items():
        if key in _RESERVED or key.startswith("_"):
            continue
        out[key] = _REDACTED if key.lower() in REDACTED_KEYS else value
    return out


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with the run id and any structured extras."""

    def format(self, record: logging.LogRecord) -> str:
        """Render the record as a single-line JSON object."""
        payload: dict[str, object] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "run_id": RUN_ID.get(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(_extras(record))
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(payload, default=str, sort_keys=False)


class TextFormatter(logging.Formatter):
    """Human-readable single line: level, run id, message, then key=value extras."""

    def format(self, record: logging.LogRecord) -> str:
        """Render the record for a terminal."""
        extras = _extras(record)
        tail = " " + " ".join(f"{k}={v}" for k, v in sorted(extras.items())) if extras else ""
        return (f"{record.levelname.lower():<7} [{RUN_ID.get()}] "
                f"{record.name}: {record.getMessage()}{tail}")


def configure_logging(level: str = "warning", fmt: str = "text",
                      stream=None) -> str:
    """Install the root handler and start a correlation id. Returns the run id.

    Logs go to stderr so that `--stdout` report output on stdout stays clean and
    pipeable. `CODESENTRY_LOG_LEVEL` / `CODESENTRY_LOG_FORMAT` override the
    arguments, which is how a CI job turns on debug logging without editing the
    command.
    """
    level = os.environ.get("CODESENTRY_LOG_LEVEL", level).lower()
    fmt = os.environ.get("CODESENTRY_LOG_FORMAT", fmt).lower()
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root = logging.getLogger("codesentry")
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False
    root.setLevel(getattr(logging, level.upper(), logging.WARNING))
    return new_run_id()


def get_logger(name: str) -> logging.Logger:
    """Child logger under the `codesentry` root."""
    return logging.getLogger(f"codesentry.{name}")
