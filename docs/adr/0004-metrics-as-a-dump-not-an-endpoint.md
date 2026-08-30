# 4. Metrics are dumped at the end of a run, not scraped from an endpoint

- Status: accepted
- Date: 2026-08-31

## Context

The tool needed an operational view of itself: how many files a run touched, how
many came from the cache, how long each phase took, how many findings and errors
it produced. Without it, the only way to answer "why did CI take four minutes
today" is to add print statements.

The obvious shape for that in 2026 is a Prometheus `/metrics` endpoint.

## Problem

codesentry is a batch process. It starts, analyzes a tree, writes a report and
exits - typically in under two seconds on a small repository. A scrape interval
is 15 to 60 seconds. A scraper would arrive after the process it wanted to
measure had already exited, and would find nothing.

## Options considered

1. **An HTTP `/metrics` endpoint** served on a background thread by
   `http.server` for the life of the run. Rejected: the run is shorter than a
   scrape interval, so it measures nothing, and it adds a listening socket, a
   thread and a port-collision failure mode to a CLI that had none.
2. **Push to a Prometheus Pushgateway** at the end of the run. Rejected as a
   default: it hardcodes an assumption that one exists and turns a fully offline
   tool into one that makes a network call. Nothing stops an operator building
   this on top of option 4.
3. **StatsD / OTLP export.** Same objection, plus a runtime dependency, which
   this package does not have and should not acquire for telemetry.
4. **Write the registry to a file when asked**, in a format an existing
   collector already understands.
5. **Log the numbers and stop there.** Partly what already happens - the run
   summary is a structured log record. Rejected as the whole answer: latency
   distributions do not fit in a log line, and counters in logs have to be
   re-derived by whatever reads them.

## Decision

Option 4. `reviewer/telemetry.py` holds an in-process `Registry` of counters and
millisecond latency histograms with fixed buckets. `--metrics-out PATH` on
`review`, `diff` and `patch` writes it as the last thing the run does:
Prometheus text exposition format by default, JSON when the path ends in
`.json`. Every series is declared up front, so a run that found nothing still
emits the series rather than an empty file a dashboard cannot key on.

Health and readiness are a separate command (`codesentry health`) for the same
reason: a probe you run is useful to a batch job, a probe you poll is not.

## Reasoning

The Prometheus text format is a file format as well as an HTTP response body.
The node exporter's textfile collector reads exactly this from a directory, a CI
job can upload it as an artifact, and `promtool` can validate it. Choosing it
costs nothing over a bespoke format and buys an existing ingestion path.

Fixed buckets rather than computed percentiles keeps the merge across runs
correct: bucket counts add, percentiles do not.

## Trade-offs

- No aggregation across runs. Each dump describes one process, and anything
  wanting a trend has to collect and merge them.
- `quantile()` returns a bucket boundary rather than an interpolated percentile.
  That is honest for a 15-bucket histogram, but it is coarse - a p95 of 250ms
  means "somewhere in (100, 250]".
- Nothing is emitted unless the operator passes `--metrics-out`, so the default
  run stays silent. Discoverability suffers in exchange for not writing files
  nobody asked for.
- A crash before the dump loses the run's metrics entirely. Timing observations
  are recorded in `finally` blocks, so phases that raised are still measured, but
  the file only exists if the process reaches the end of the command.

## Consequences

- The registry is process-local and in-memory: no background thread, no socket,
  no persistence, nothing to fail at start-up.
- `tests/test_integration.py` asserts the dumped counters agree with the JSON
  report from the same run - files analyzed matches files reviewed, findings by
  severity matches the summary. A metrics surface nobody cross-checks drifts.
- If a long-running mode ever appears (a watch mode, a language-server), this
  decision should be revisited; option 1 becomes correct the moment the process
  outlives a scrape interval.
