"""Deterministic generator for the bundled demo repository.

The demo repo is not decoration: it is the *ground truth* the smoke test scores
against. Every deliberate defect is planted through `_File.emit(..., plants=...)`,
which resolves a marker substring to the line it lands on, so the manifest always
carries the exact `file:line` even after the surrounding code is edited. Files
listed in `clean_files` are written to be defect-free, which turns the demo into a
precision test as well as a recall test.

Two versions of the repo are emitted - `base/` and `head/` - so the diff-aware
review has a real before/after to work with.
"""
from __future__ import annotations

import json
import os
import textwrap
from dataclasses import dataclass, field

from .analyzers import RULES


@dataclass(frozen=True)
class Plant:
    """One deliberately planted defect, with the location the reviewer must report."""

    file: str
    line: int
    rule: str
    category: str
    introduced: bool = False   # only present in the head revision (diff-mode target)

    @property
    def key(self) -> tuple[str, int, str]:
        """Identity shared with `Finding.key` so scoring is a set operation."""
        return (self.file, self.line, self.rule)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {"file": self.file, "line": self.line, "rule": self.rule,
                "category": self.category, "introduced": self.introduced}


@dataclass
class DemoManifest:
    """Ground truth for one generated repo version."""

    root: str
    files: dict[str, str] = field(default_factory=dict)
    plants: list[Plant] = field(default_factory=list)
    clean_files: tuple[str, ...] = ()

    def plants_for(self, file: str) -> list[Plant]:
        """Planted defects belonging to one file."""
        return [p for p in self.plants if p.file == file]

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {"root": self.root, "clean_files": list(self.clean_files),
                "plants": [p.to_dict() for p in self.plants]}


class _File:
    """Accumulates source lines while recording the line each planted defect lands on."""

    def __init__(self, path: str):
        self.path = path
        self.lines: list[str] = []
        self.plants: list[Plant] = []

    def emit(self, text: str, plants: tuple[tuple[str, str], ...] = (),
             introduced: bool = False) -> None:
        """Append a dedented block; each (rule, marker) plant anchors to its line."""
        block = textwrap.dedent(text).strip("\n").split("\n")
        base = len(self.lines)
        for rule, marker in plants:
            offsets = [i for i, line in enumerate(block) if marker in line]
            if not offsets:
                raise ValueError(f"marker {marker!r} not found in block for {self.path}")
            self.plants.append(Plant(self.path, base + offsets[0] + 1, rule,
                                     RULES[rule].category, introduced))
        self.lines.extend(block)

    def source(self) -> str:
        """Final file text (newline terminated)."""
        return "\n".join(self.lines) + "\n"


def _gateway(_head: bool) -> _File:
    """Security defects: secrets, injection sinks and unsafe deserialization."""
    f = _File("payments/gateway.py")
    f.emit('''
        """Card charging and payout helpers for the billing service."""
        import os
        import pickle
        import subprocess

        API_TOKEN = "sk_live_9f3a2b7c4d5e6f70"
    ''', (("hardcoded-secret", "API_TOKEN ="),))
    f.emit('''


        def ledger_path():
            """Return the ledger directory configured for this deployment."""
            return os.path.join(os.environ.get("LEDGER_HOME", "."), "ledger")


        def charge_customer(cursor, customer_id, amount_cents):
            """Insert a charge row and return the new charge id."""
            sql = "INSERT INTO charges (customer, cents) VALUES ('" + customer_id + "')"
            cursor.execute(sql, amount_cents)
            return cursor.lastrowid


        def refund(cursor, charge_id):
            """Remove a charge that was reversed by the customer."""
            cursor.execute(f"DELETE FROM charges WHERE id = {charge_id}")
            return True


        def apply_discount_rule(rule_text, total):
            """Apply a pricing rule authored by the operations team."""
            return eval(rule_text) * total


        def sync_ledger(remote_host):
            """Mirror the local ledger directory to the reporting host."""
            subprocess.run("rsync -a ledger/ " + remote_host, shell=True, check=True)


        def rotate_logs():
            """Roll the gateway log file over."""
            os.system("mv gateway.log gateway.log.1")


        def load_session(blob):
            """Restore a checkout session from its cached representation."""
            return pickle.loads(blob)
    ''', (
        ("sql-injection", 'sql = "INSERT'),
        ("sql-injection", "DELETE FROM charges"),
        ("eval-exec", "eval(rule_text)"),
        ("shell-true", "shell=True"),
        ("os-system", "os.system("),
        ("unsafe-deserialization", "pickle.loads("),
    ))
    return f


def _validation(_head: bool) -> _File:
    """Correctness defects around argument handling and control flow."""
    f = _File("payments/validation.py")
    f.emit('''
        """Input validation for inbound payment requests."""

        SUPPORTED = ("USD", "EUR", "GBP")


        def validate_amount(amount_cents, currency):
            """Check the amount is inside the band the processor accepts."""
            assert amount_cents > 0, "amount must be positive"
            return amount_cents, currency


        def collect_errors(request, errors=[]):
            """Append validation problems for one request and return the list."""
            if request.get("currency") is "USD":
                errors.append("usd payments require a tax id")
            if request.get("amount") in (None, 0):
                errors.append("amount is missing")
            return errors


        def normalize_status(status):
            """Translate a gateway status into our internal vocabulary."""
            if status == "ok":
                return "settled"
            if status == "pending":
                return "authorized"
            if status == "failed":
                return "declined"
    ''', (
        ("assert-validation", "assert amount_cents"),
        ("mutable-default", "def collect_errors("),
        ("is-literal", 'is "USD"'),
        ("inconsistent-return", "def normalize_status("),
    ))
    return f


def _stock(head: bool) -> _File:
    """Resource, boundary and exception-handling defects."""
    f = _File("inventory/stock.py")
    if head:
        f.emit('''
            """Stock level bookkeeping for the warehouse service."""
            import subprocess
        ''')
    else:
        f.emit('''
            """Stock level bookkeeping for the warehouse service."""
        ''')
    f.emit('''


        def read_counts(path):
            """Load the stock counts recorded by the night job."""
            handle = open(path, "r", encoding="utf-8")
            rows = handle.read().splitlines()
            return rows


        def find_gaps(levels):
            """Report positions where stock drops between neighbouring days."""
            gaps = []
            for i in range(len(levels)):
                if levels[i] > levels[i + 1]:
                    gaps.append(i)
            return gaps


        def last_level(levels):
            """Return the most recently recorded stock level."""
            return levels[len(levels)]


        def reorder_point(daily_usage, lead_days):
            """Compute the reorder point, tolerating malformed inputs."""
            try:
                return daily_usage * lead_days
            except:
                return 0


        def persist(rows, path):
            """Write stock rows to disk, ignoring transient IO problems."""
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("\\n".join(rows))
            except Exception:
                pass


        def summarize(list):
            """Total the quantities held in a batch of stock rows."""
            total = 0
            for row in list:
                total += row
            doubled = total * 2
            return total
    ''', (
        ("unclosed-resource", "handle = open("),
        ("off-by-one", "levels[i + 1]"),
        ("off-by-one", "levels[len(levels)]"),
        ("bare-except", "except:"),
        ("broad-except", "except Exception:"),
        ("shadowed-builtin", "def summarize("),
        ("unused-variable", "doubled ="),
    ))
    if head:
        f.emit('''


            def export_snapshot(target_host, path):
                """Copy the stock snapshot to the reporting host."""
                subprocess.run("scp " + path + " " + target_host, shell=True, check=True)
        ''', (("shell-true", "shell=True"),), introduced=True)
    return f


def _reporting(_head: bool) -> _File:
    """Complexity defects: one over-parameterised, deeply nested, over-long function."""
    f = _File("inventory/reporting.py")
    f.emit('''
        """Weekly warehouse reporting."""
        import collections
        import datetime
        import decimal
        import functools
        import itertools
        import json
        import math
        import os
        import random
        import statistics
        import sys
        import textwrap
        import time
    ''', (("high-coupling", '"""Weekly warehouse reporting."""'),))
    f.emit('''


        def build_report(rows, start, end, region, currency, precision, seed, verbose):
            """Render the weekly stock report for one region as a text block."""
            random.seed(seed)
            started = time.time()
            buckets = collections.defaultdict(list)
            lines = ["region: " + region, "currency: " + currency]
            for row in rows:
                if row.get("region") == region:
                    for key in sorted(row):
                        if key.startswith("qty_"):
                            if row[key] is not None:
                                if row[key] > 0:
                                    buckets[key].append(row[key])
                                else:
                                    buckets[key].append(0)
            for key in sorted(buckets):
                values = buckets[key]
                if not values:
                    continue
                mean = statistics.fmean(values)
                if len(values) > 1:
                    spread = statistics.pstdev(values)
                else:
                    spread = 0.0
                quant = decimal.Decimal(10) ** -precision
                scaled = decimal.Decimal(mean).quantize(quant)
                lines.append("{0}: mean={1} spread={2:.2f}".format(key, scaled, spread))
                if verbose:
                    ranked = sorted(values, reverse=True)[:3]
                    for rank, value in enumerate(ranked, 1):
                        lines.append("    #{0} {1}".format(rank, value))
            window = (end - start) if end > start else 1
            per_day = functools.reduce(lambda a, b: a + b,
                                       [len(v) for v in buckets.values()], 0) / window
            lines.append("samples per day: {0:.3f}".format(per_day))
            lines.append("sqrt spread: {0:.3f}".format(math.sqrt(max(per_day, 0.0))))
            pairs = list(itertools.islice(itertools.combinations(sorted(buckets), 2), 5))
            for left, right in pairs:
                overlap = set(buckets[left]) & set(buckets[right])
                if overlap:
                    lines.append("overlap {0}/{1}: {2}".format(left, right, len(overlap)))
                else:
                    lines.append("overlap {0}/{1}: none".format(left, right))
            totals = {key: sum(values) for key, values in buckets.items()}
            ranked_totals = sorted(totals.items(), key=lambda kv: -kv[1])
            grand_total = max(sum(totals.values()), 1)
            for position, (key, total) in enumerate(ranked_totals[:5], 1):
                share = total / grand_total
                if share > 0.5:
                    label = "dominant"
                elif share > 0.2:
                    label = "significant"
                else:
                    label = "minor"
                lines.append("{0}. {1} total={2} share={3:.1%} ({4})".format(
                    position, key, total, share, label))
            stamp = datetime.datetime.fromtimestamp(started).isoformat(timespec="seconds")
            lines.append("generated: " + stamp)
            lines.append("host: " + os.environ.get("HOSTNAME", "unknown"))
            lines.append("python: " + sys.version.split()[0])
            lines.append("payload: " + json.dumps({"buckets": len(buckets)}))
            body = "\\n".join(lines)
            if verbose:
                body = textwrap.indent(body, "  ")
            return body
    ''', (
        ("too-many-params", "def build_report("),
        ("high-complexity", "def build_report("),
        ("deep-nesting", "def build_report("),
        ("long-function", "def build_report("),
    ))
    return f


def _legacy(_head: bool) -> _File:
    """Maintainability defects: no docstrings, dead code, TODO, dead imports, clones."""
    f = _File("utils/legacy.py")
    f.emit('''
        import hashlib
        import json

        # TODO: delete this module once the v2 exporter ships
    ''', (
        ("missing-docstring", "import hashlib"),
        ("unused-import", "import hashlib"),
        ("todo-marker", "# TODO:"),
    ))
    f.emit('''


        def flatten_rows(rows):
            result = []
            for row in rows:
                if isinstance(row, dict):
                    for key in sorted(row):
                        value = row[key]
                        if value is None:
                            result.append((key, ""))
                        else:
                            result.append((key, str(value)))
                else:
                    result.append(("value", str(row)))
            result.sort()
            return result
            result.clear()


        def dump_rows(rows):
            """Serialise flattened rows as a JSON document."""
            return json.dumps(flatten_rows(rows))


        def _stale_checksum(text):
            return len(text) % 97
    ''', (
        ("missing-docstring", "def flatten_rows("),
        ("duplicate-block", "def flatten_rows("),
        ("dead-code", "result.clear()"),
        ("unused-private", "def _stale_checksum("),
    ))
    return f


def _helpers(_head: bool) -> _File:
    """Clone source for the duplicate-block rule; otherwise clean."""
    f = _File("utils/helpers.py")
    f.emit('''
        """Row shaping helpers used by the exporter."""


        def expand_records(records):
            """Flatten records into sorted (key, text) pairs."""
            output = []
            for record in records:
                if isinstance(record, dict):
                    for field_name in sorted(record):
                        item = record[field_name]
                        if item is None:
                            output.append((field_name, ""))
                        else:
                            output.append((field_name, str(item)))
                else:
                    output.append(("value", str(record)))
            output.sort()
            return output
    ''')
    return f


def _config(head: bool) -> _File:
    """Clean file: the precision check fails if the reviewer flags anything here."""
    f = _File("core/config.py")
    timeout = "45" if head else "30"
    f.emit(f'''
        """Runtime configuration for the warehouse service."""
        from dataclasses import dataclass

        DEFAULT_TIMEOUT_SECONDS = {timeout}


        @dataclass(frozen=True)
        class ServiceConfig:
            """Connection settings shared by every warehouse worker."""

            host: str
            port: int
            timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

            def endpoint(self) -> str:
                """Return the base URL the workers should call."""
                return "http://{{0}}:{{1}}".format(self.host, self.port)


        def load_config(env):
            """Build a ServiceConfig from an environment mapping."""
            host = env.get("WAREHOUSE_HOST", "localhost")
            port = int(env.get("WAREHOUSE_PORT", "8080"))
            timeout = int(env.get("WAREHOUSE_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
            return ServiceConfig(host=host, port=port, timeout_seconds=timeout)
    ''')
    return f


def _models(_head: bool) -> _File:
    """Clean file: idiomatic dataclasses with full docstrings."""
    f = _File("core/models.py")
    f.emit('''
        """Domain models for warehouse stock."""
        from dataclasses import dataclass, field


        @dataclass
        class StockItem:
            """A single SKU held in one warehouse."""

            sku: str
            quantity: int
            reserved: int = 0

            def available(self) -> int:
                """Return the quantity that can still be promised to customers."""
                return max(self.quantity - self.reserved, 0)


        @dataclass
        class Warehouse:
            """A named warehouse holding a set of stock items."""

            name: str
            items: list = field(default_factory=list)

            def total_available(self) -> int:
                """Return the promisable quantity across every stocked item."""
                return sum(item.available() for item in self.items)

            def find(self, sku):
                """Return the item with this SKU, or None when it is not stocked."""
                for item in self.items:
                    if item.sku == sku:
                        return item
                return None
    ''')
    return f


_PACKAGE_DOCS = {
    "payments/__init__.py": "Payment gateway package.",
    "inventory/__init__.py": "Inventory and reporting package.",
    "utils/__init__.py": "Shared helpers package.",
    "core/__init__.py": "Core configuration and domain models.",
}

_BUILDERS = (_gateway, _validation, _stock, _reporting, _legacy, _helpers,
             _config, _models)

CLEAN_FILES = ("core/config.py", "core/models.py", "utils/helpers.py",
               "payments/__init__.py", "inventory/__init__.py",
               "utils/__init__.py", "core/__init__.py")

#: A credential the AST passes cannot see - only the agent's search_pattern tool
#: reaches non-Python files, which is what makes the agent layer load-bearing.
SETTINGS_INI = (
    "[gateway]\n"
    "endpoint = https://api.example.com/v1\n"
    "stripe_secret_key = sk_live_4b81c0d9e7f2a635\n"
    "retries = 3\n"
)
SETTINGS_SECRET_LINE = 3


def build_manifest(root: str, head: bool = False) -> DemoManifest:
    """Build the in-memory repo (sources + ground truth) without touching disk."""
    files: dict[str, str] = {}
    plants: list[Plant] = []
    for builder in _BUILDERS:
        made = builder(head)
        files[made.path] = made.source()
        plants.extend(made.plants)
    for path, doc in _PACKAGE_DOCS.items():
        files[path] = f'"""{doc}"""\n'
    files["payments/settings.ini"] = SETTINGS_INI
    # Reachable only through the agent's search_pattern tool: no AST pass parses .ini.
    plants.append(Plant("payments/settings.ini", SETTINGS_SECRET_LINE,
                        "hardcoded-secret", RULES["hardcoded-secret"].category))
    plants.sort(key=lambda p: (p.file, p.line, p.rule))
    return DemoManifest(root=root, files=files, plants=plants, clean_files=CLEAN_FILES)


def write_demo_repo(root: str, head: bool = False, seed: int = 42) -> DemoManifest:
    """Materialise the demo repo under `root` and drop a manifest.json beside it.

    `seed` is accepted for interface symmetry with the rest of the portfolio; the
    generator is fully deterministic, so the same bytes are written every run.
    """
    manifest = build_manifest(root, head=head)
    for rel, text in manifest.files.items():
        dest = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest.to_dict(), handle, indent=2)
    return manifest


def write_demo_pair(base_dir: str, seed: int = 42) -> tuple[DemoManifest, DemoManifest]:
    """Write both repo versions (`base/` and `head/`) used by the diff-aware demo."""
    base_root = os.path.join(base_dir, "base")
    head_root = os.path.join(base_dir, "head")
    return (write_demo_repo(base_root, head=False, seed=seed),
            write_demo_repo(head_root, head=True, seed=seed))
