"""The negative half of the corpus: benign code that a naive rule would flag.

Recall is trivially gamed by reporting everything, so a detection rate is only
meaningful next to a false-positive rate - and a false-positive rate is only
meaningful if the benign files are actually hard. Three hand-written files that
happen to avoid the rules under test measure nothing.

Every file here is deliberately adversarial. For each rule there is at least one
construct that shares the *shape* the rule looks for while being correct code a
reviewer would approve: `API_KEY_HEADER = "X-Api-Key"` for the secret rule, the
pairwise `range(len(xs) - 1)` loop for off-by-one, `ast.literal_eval` for
eval/exec, a function sitting exactly on the complexity threshold rather than
one over it.

Every finding reported on any of these files is counted as a false positive by
`codesentry eval`, and the numbers in the README come from that command. When a
case here starts firing, the honest options are to fix the rule or to delete the
case with a note saying the rule is right; suppressing it is not one of them.
"""
from __future__ import annotations

import textwrap

#: rel path -> source. Written into the corpus and listed as benign, so any
#: finding on one of them is a false positive by construction.
NEGATIVE_FILES: dict[str, str] = {}


def _add(path: str, source: str) -> None:
    NEGATIVE_FILES[path] = textwrap.dedent(source).strip("\n") + "\n"


_add("negatives/__init__.py", '''
    """Benign near-miss corpus: correct code shaped like the defects."""
''')

# --- security near-misses -------------------------------------------------
_add("negatives/security_lookalikes.py", '''
    """Correct security-sensitive code that shares its shape with the defects."""
    import ast
    import hashlib
    import json
    import os
    import subprocess

    #: Names of things, not the things themselves. The secret rule keys off the
    #: identifier, so these are the constants it must not fire on.
    API_KEY_HEADER = "X-Api-Key"
    TOKEN_ENV_VAR = "MYAPP_ACCESS_TOKEN"
    PASSWORD_FIELD = "user_password"
    SECRET_PLACEHOLDER = "changeme"
    API_KEY_PATTERN = "^sk_[a-z]+_[A-Za-z0-9]+$"


    def load_api_key():
        """Read the credential from the environment rather than the source."""
        return os.environ[TOKEN_ENV_VAR]


    def parse_rule(rule_text):
        """Evaluate a literal expression without compiling arbitrary code."""
        return ast.literal_eval(rule_text)


    def load_payload(raw):
        """Deserialize untrusted bytes with a format that cannot build objects."""
        return json.loads(raw)


    def sync_ledger(remote_host):
        """Copy the ledger without handing an interpolated string to a shell."""
        return subprocess.run(["rsync", "-a", "ledger/", remote_host], check=True)


    def digest(blob):
        """Hash content with a function that is not collision-broken."""
        return hashlib.sha256(blob).hexdigest()


    def cache_key(blob):
        """Non-cryptographic digest, declared as such to the hashlib API."""
        return hashlib.md5(blob, usedforsecurity=False).hexdigest()


    def find_customer(cursor, customer_id):
        """Parameterised query: the value never becomes part of the statement."""
        cursor.execute("SELECT id, name FROM customers WHERE id = ?", (customer_id,))
        return cursor.fetchone()


    def describe_refresh(count):
        """Prose that merely contains SQL keywords is not a SQL statement."""
        return "update the local cache for " + str(count) + " customers"


    def selection_note(field):
        """More prose: 'select' and 'from' in an English sentence."""
        return "select the value from the configured field: " + field
''')

# --- correctness near-misses ---------------------------------------------
_add("negatives/correctness_lookalikes.py", '''
    """Correct control flow that resembles the correctness defects."""
    import contextlib


    def append_item(item, bucket=None):
        """Default argument is immutable; the list is built per call."""
        if bucket is None:
            bucket = []
        bucket.append(item)
        return bucket


    def coordinates(point=()):
        """An empty tuple default is shared safely because it cannot be mutated."""
        return list(point)


    def retry_once(action):
        """Catching a narrow exception and re-raising keeps the failure visible."""
        try:
            return action()
        except OSError:
            raise


    def report_failure(action, log):
        """Broad catch is fine when the error is logged and re-raised."""
        try:
            return action()
        except Exception as exc:
            log.error("action failed: %s", exc)
            raise


    def classify(value):
        """`is` against None is identity by design, not a literal comparison."""
        if value is None:
            return "missing"
        if type(value) is type(True):
            return "flag"
        return "value"


    def totals(rows):
        """Underscore discards are intentional, not forgotten assignments."""
        total = 0
        for _index, amount in rows:
            total += amount
        _ = len(rows)
        return total


    def pairwise_gaps(values):
        """range(len - 1) with i + 1 is the correct pairwise idiom."""
        gaps = []
        for i in range(len(values) - 1):
            gaps.append(values[i + 1] - values[i])
        return gaps


    def last_index(values):
        """len() - 1 is the last valid index, not one past the end."""
        if not values:
            return -1
        return values[len(values) - 1]


    def grade(score):
        """Every path returns, including the one that raises."""
        if score < 0:
            raise ValueError("score cannot be negative")
        if score > 90:
            return "A"
        return "B"


    def read_config(path):
        """The handle is managed by a context manager."""
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()


    def read_legacy(path):
        """try/finally closes the handle on every path, including exceptions."""
        handle = open(path, encoding="utf-8")
        try:
            return handle.read()
        finally:
            handle.close()


    def read_closing(path):
        """contextlib.closing manages a handle the caller did not open with `with`."""
        with contextlib.closing(open(path, encoding="utf-8")) as handle:
            return handle.read()


    def open_log(path):
        """Returning the handle hands ownership to the caller, who closes it."""
        return open(path, "a", encoding="utf-8")
''')

# --- shadowing and naming -------------------------------------------------
_add("negatives/naming_lookalikes.py", '''
    """Names that resemble builtins without shadowing any."""


    class Record:
        """A row with fields whose names only look like builtins."""

        def __init__(self, record_id, record_type):
            self.id = record_id
            self.type = record_type
            self._cache = {}

        def as_dict(self):
            """Attribute access is not a scope binding, so `self.id` is fine."""
            return {"id": self.id, "type": self.type}

        def cached(self, key, build):
            """Private state is used, so `_cache` is not a dead attribute."""
            if key not in self._cache:
                self._cache[key] = build()
            return self._cache[key]


    def filter_rows(rows, list_of_ids):
        """Trailing and prefixed names avoid shadowing `filter` and `list`."""
        filter_ = set(list_of_ids)
        return [row for row in rows if row.id in filter_]


    def _normalise(value):
        """Private helper with a caller, so it is not dead weight."""
        return value.strip().lower()


    def normalise_all(values):
        """Public entry point that uses the private helper above."""
        return [_normalise(v) for v in values]
''')

# --- complexity boundary cases -------------------------------------------
_add("negatives/threshold_lookalikes.py", '''
    """Functions sitting exactly on the default thresholds, not one over them."""


    def route(kind, flag_a, flag_b, flag_c, flag_d, flag_e):
        """Six parameters is the documented maximum, so this must not fire."""
        return (kind, flag_a, flag_b, flag_c, flag_d, flag_e)


    def classify(value, mode, limit):
        """Cyclomatic complexity nine: one under the default ceiling of ten."""
        if value is None:
            return "empty"
        if mode == "strict" and value > limit:
            return "over"
        if mode == "loose" or value == limit:
            return "edge"
        if value < 0:
            return "negative"
        if value > limit * 2:
            return "far-over"
        if value % 2 == 0:
            return "even"
        return "odd"


    def walk(tree, depth_limit):
        """Nesting depth four: the default maximum, not a violation of it."""
        found = []
        for branch in tree:
            if branch:
                for leaf in branch:
                    if leaf < depth_limit:
                        found.append(leaf)
        return found


    def dispatch(kind, payload, strict):
        """Cyclomatic complexity ten: exactly the ceiling, so it must not fire."""
        if kind == "a":
            return payload
        if kind == "b" and strict:
            return payload[::-1]
        if kind == "c" or strict:
            return list(payload)
        if kind == "d":
            return tuple(payload)
        if kind == "e":
            return set(payload)
        if kind == "f":
            return dict.fromkeys(payload)
        if kind == "g":
            return len(payload)
        return None
''')

# --- textual rules --------------------------------------------------------
_add("negatives/text_lookalikes.py", '''
    """Cases for the two rules that are textual rather than AST-based."""
    from __future__ import annotations

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from collections.abc import Sequence

    #: 110 characters exactly, which is the default ceiling rather than over it.
    BANNER = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    HELP_TEXT = "Add the item to your TODO list before the sprint review."


    def render(items: Sequence[str]) -> str:
        """Annotation-only import is used, so it is not a dead import."""
        return ", ".join(items)


    def banner_width() -> int:
        """The long constant above is exactly at the limit, not past it."""
        return len(BANNER)
''')

# --- maintainability near-misses -----------------------------------------
_add("negatives/maintainability_lookalikes.py", '''
    """Maintainability shapes that are conventional rather than defective."""
    from collections import OrderedDict
    from dataclasses import dataclass

    __all__ = ["Settings", "ordered_settings", "describe"]


    @dataclass
    class Settings:
        """Configuration values resolved once at start-up."""

        endpoint: str
        retries: int = 3


    def ordered_settings(pairs):
        """Uses OrderedDict, so the import above is not dead."""
        return OrderedDict(sorted(pairs))


    def describe(settings):
        """Docstrings mentioning a to-do list are prose, not TODO markers."""
        return f"{settings.endpoint} retrying {settings.retries} times"


    def poll(source, limit):
        """`break` ends the loop; the code after it is reached, not dead."""
        seen = []
        while True:
            item = source()
            if item is None:
                break
            seen.append(item)
            if len(seen) >= limit:
                break
        return seen


    def summarise(rows):
        """Similar in spirit to `tally` below, but not a copy of it."""
        return {"count": len(rows), "first": rows[0] if rows else None}


    def tally(rows, key):
        """Groups by a key; shares no token sequence with `summarise`."""
        buckets = {}
        for row in rows:
            buckets.setdefault(getattr(row, key), []).append(row)
        return buckets
''')
