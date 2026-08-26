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
    body = "\n".join(lines)
    if verbose:
        body = textwrap.indent(body, "  ")
    return body
