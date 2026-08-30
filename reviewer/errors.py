"""Error taxonomy and the process exit-code contract.

Every failure the tool can produce is one of these classes, and each class maps
to exactly one exit code. That is what makes the CLI usable in CI: a script can
tell "the gate failed" (1) from "you invoked me wrong" (2) from "I broke" (3)
without parsing text.

    0  clean run, no gate tripped
    1  a gate failed (findings above the threshold, health below --fail-under)
    2  usage, configuration or input problem - the caller can fix it
    3  internal failure - a file could not be analyzed, the cache is unusable

`AnalysisError` matters most. A static analyzer that says "no findings" when it
actually crashed is worse than no analyzer, so an analyzer failure is never
swallowed: it is collected, reported in every output format, and forces exit 3.
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3


class CodeSentryError(Exception):
    """Base class: carries a stable slug, an exit code and structured details."""

    code = "error"
    exit_code = EXIT_INTERNAL

    def __init__(self, message: str, **details: object):
        super().__init__(message)
        self.message = message
        self.details: dict[str, object] = dict(details)

    def to_dict(self) -> dict:
        """Machine-readable form, embedded in JSON/SARIF output."""
        return {"code": self.code, "message": self.message, "details": self.details}

    def __str__(self) -> str:
        if not self.details:
            return self.message
        extra = ", ".join(f"{k}={v}" for k, v in sorted(self.details.items()))
        return f"{self.message} ({extra})"


class UsageError(CodeSentryError):
    """The command line itself is wrong (unknown rule, contradictory flags)."""

    code = "usage"
    exit_code = EXIT_USAGE


class ConfigError(CodeSentryError):
    """A config file exists but cannot be parsed or contains unknown keys."""

    code = "config"
    exit_code = EXIT_USAGE


class InputError(CodeSentryError):
    """A path does not exist, escapes the review root, or cannot be read."""

    code = "input"
    exit_code = EXIT_USAGE


class AnalysisError(CodeSentryError):
    """One file could not be analyzed. Never swallowed; forces a non-zero exit."""

    code = "analysis"
    exit_code = EXIT_INTERNAL

    def __init__(self, message: str, file: str = "", **details: object):
        super().__init__(message, file=file, **details)
        self.file = file

    def to_dict(self) -> dict:
        """Machine-readable form including the file that failed."""
        data = super().to_dict()
        data["file"] = self.file
        return data


class CacheError(CodeSentryError):
    """The result cache is unusable (corrupt file, unsupported schema version)."""

    code = "cache"
    exit_code = EXIT_INTERNAL


class ToolInputError(CodeSentryError):
    """An agent tool was called with arguments outside its contract.

    Under `--planner llm` these arguments are model-generated, so they are
    untrusted input and get rejected with a message rather than crashing.
    """

    code = "tool-input"
    exit_code = EXIT_USAGE
