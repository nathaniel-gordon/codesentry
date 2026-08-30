# Deployment

**Nothing is deployed.** There is no hosted service, no published image, no
package on PyPI and no live URL. This document describes how the artifacts in
this repository are meant to be run, and every command in it was executed on the
author's machine (Windows 10, Docker 29.6.1, Python 3.14) unless it is marked
otherwise. Where something has not been run, it says so.

## The target, and why

**GitHub Actions, with the analyzer running as a step inside the job that already
checked out the code.** The container image is the general form of the same
thing for any CI that can run one; `pip install` is the local form.

The reasoning is in [ADR 0005](adr/0005-ship-a-cli-container-not-a-service.md).
Briefly: the analyzer needs the source, a CPU and somewhere to put a report. CI
has all three and already holds an identity with the right to read the code. A
hosted service would have to be handed the source and the credentials, which
turns an offline batch tool into a system with data-custody obligations and
uptime, for no capability the tool actually needs.

This is one process, with no listener, no dependencies and no shared state, so
there is no `docker-compose.yml` here - see the same ADR.

## Prerequisites

| | version | why |
|---|---|---|
| Python | 3.11+ | declared floor in `pyproject.toml`; `tomllib` is 3.11 |
| Docker | any recent | only for the container path; built here with 29.6.1 |
| git | optional | churn ranking uses `git log --numstat`; without it the model falls back to a static structural proxy and `codesentry health` reports the check as `skipped` |

No runtime dependencies outside the standard library. `anthropic` is needed only
for `--mode agent --planner llm`, and nothing else in the tool touches the
network.

## Environment variables

All optional. `.env.example` carries the same list.

| variable | default | effect |
|---|---|---|
| `CODESENTRY_LOG_LEVEL` | `warning` | `debug`, `info`, `warning`, `error`. Overrides `--log-level`. |
| `CODESENTRY_LOG_FORMAT` | `text` | `text` or `json`. Overrides `--log-format`. Set to `json` in CI. |
| `CODESENTRY_CACHE` | `<root>/.codesentry-cache/cache.db` | absolute path to the result cache. |
| `ANTHROPIC_API_KEY` | unset | only read under `--mode agent --planner llm`. Without it that mode degrades to the deterministic planner and says so in the report. |
| `CLAUDE_MODEL` | `claude-opus-5` | model for the optional planner. |

The image sets `CODESENTRY_LOG_FORMAT=json` and points `CODESENTRY_CACHE` at
`/tmp/codesentry-cache/cache.db`, because `/work` is a bind mount that may be
read-only.

Logs go to stderr. Report output on stdout stays clean and pipeable.

## Migrations

The only persistent state is the SQLite result cache, and it migrates itself.

- Opening a cache applies any pending forward migrations, one transaction per
  step, recorded in a `schema_version` table. Nothing to run by hand.
- Opening a cache written by a **newer** build is refused with a `CacheError` and
  exit 3, rather than guessed at. Delete it, or pass `--clear-cache`.
- The cache key includes the analyzer version, so an upgrade invalidates every
  entry rather than serving stale answers. A downgrade is safe for the same
  reason, *unless* the newer build also bumped the schema - then the old build
  refuses to open the file and you delete it.

The cache is a performance aid, never a source of truth. Deleting it costs one
cold run:

```bash
codesentry cache . --clear
```

## Build

### The wheel

```bash
python -m pip install --upgrade build
python -m build --wheel
```

### The image

```bash
docker build -t codesentry:0.3.0 .
```

Run here; the build succeeds. `docker images` reports **332MB** for the result -
`python:3.12-slim` plus `git` and its dependencies. Two stages: the builder makes
the wheel, the runtime layer installs it and carries no build backend.

Verified after building:

```
$ docker run --rm --entrypoint sh codesentry:0.3.0 -c 'id'
uid=10001(sentry) gid=10001(sentry) groups=10001(sentry)

$ docker run --rm codesentry:0.3.0 health --probe liveness
liveness: ok (codesentry 0.3.0, analyzer 0.3.0+r4)
```

## Deploy

### GitHub Actions (the documented target)

```yaml
name: code review
on: [pull_request]

permissions:
  contents: read
  security-events: write

jobs:
  codesentry:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0        # churn reads git history; a shallow clone has none
      - uses: nathaniel-gordon/codesentry@v0.3.0
        with:
          paths: src
          fail-on-severity: high
```

`action.yml` is a composite action: it installs the package, runs the analyzer,
and uploads the SARIF to code scanning. **This has not run on GitHub.** Nothing
in this repository has been pushed, so there is no workflow run to point at. The
YAML parses and the underlying commands are the ones exercised locally and in
`tests/test_integration.py`; that is the extent of it.

Pin the `rev`/tag rather than tracking a branch. Rule behaviour changes between
versions, and an unpinned analyzer is a build that can start failing without a
commit.

### Any CI, via the image

```bash
docker run --rm \
  -v "$PWD:/work/repo:ro" \
  -v "$PWD/reports:/work/reports" \
  codesentry:0.3.0 review repo \
    --format sarif --format json --out /work/reports \
    --fail-on-severity high \
    --metrics-out /work/reports/run.prom
```

Mount the checkout read-only; the tool never writes to the tree it reviews (there
is an invariant test asserting exactly that). Mount a separate writable directory
for reports.

To keep the cache warm across jobs, mount a directory for it and point
`CODESENTRY_CACHE` at a file inside:

```bash
-v "$HOME/.cache/codesentry:/cache" -e CODESENTRY_CACHE=/cache/cache.db
```

### Locally, or as a pre-commit hook

```bash
pip install codesentry            # not published; use `pip install -e .` from a checkout
codesentry review src/
```

```yaml
repos:
  - repo: https://github.com/nathaniel-gordon/codesentry
    rev: v0.3.0
    hooks:
      - id: codesentry
```

`pre-commit try-repo` has **not** been run here - pre-commit is not installed in
this environment. What is verified is the hook's exact command contract and the
installability of the package, not pre-commit's venv bootstrap.

## Health checks

```bash
codesentry health --probe liveness     # install integrity only, no filesystem
codesentry health                      # readiness: config, cache, output dir, git
codesentry health --json               # same, machine-readable
```

Exit 0 when every check passes, 3 when any fails - 3 rather than 1 because a
failing probe means the install or the environment is broken, not that the
analyzer found something.

| check | probe | fails when |
|---|---|---|
| `python` | both | never (informational) |
| `rule-table` | both | the rule table is empty |
| `rule-packs` | both | a rule is in no pack, or in two |
| `rule-vocabulary` | both | a rule's severity or category is out of vocabulary |
| `config` | readiness | `[tool.codesentry]` is unparseable or has unknown keys |
| `cache` | readiness | the cache file is corrupt or written by a newer build |
| `output-writable` | readiness | the report directory cannot be written |
| `git` | readiness | never - reports `skipped` when git is absent |

The image's HEALTHCHECK runs the **liveness** probe, because `/work` is whatever
the caller mounted and may legitimately be empty or read-only. Verified on a
container held open with `--entrypoint sleep`:

```
$ docker inspect --format '{{.State.Health.Status}}' cs-health
healthy
```

Run readiness in CI as its own step before a long analysis, so a bad config fails
in two seconds instead of two minutes.

## Observability

Structured logs, on stderr, one JSON object per line, every record carrying the
same 12-character `run_id` for the run:

```bash
codesentry review src/ --log-level info --log-format json
```

```json
{"ts": "2026-08-30T22:27:46", "level": "info", "run_id": "2e6db691c4b4", "logger": "codesentry.scan", "event": "review finished", "files": 27, "findings": 32, "errors": 0, "elapsed_ms": 114.7, "cache_hits": 27, "cache_misses": 0}
```

A fixed key list (`api_key`, `token`, `password`, `secret`, `source`, ...) is
redacted to `***` in every record, in both formats.

Counters and latency histograms are dumped at the end of a run:

```bash
codesentry review src/ --metrics-out reports/run.prom     # Prometheus text
codesentry review src/ --metrics-out reports/run.json     # same data as JSON
```

Emitted series - and only these, because these are the ones the code actually
records:

| series | type | labels |
|---|---|---|
| `codesentry_files_analyzed_total` | counter | `source` = `parsed` \| `cache` |
| `codesentry_cache_events_total` | counter | `result` = `hit` \| `miss` \| `off` |
| `codesentry_findings_total` | counter | `severity`, `category` |
| `codesentry_analyzer_errors_total` | counter | `reason` (exception class) |
| `codesentry_suppressed_findings_total` | counter | `mechanism` = `by_pragma` \| `by_baseline` |
| `codesentry_file_analysis_duration_ms` | histogram | - |
| `codesentry_phase_duration_ms` | histogram | `phase` = `analyze` \| `duplicates` \| `secrets` |
| `codesentry_run_duration_ms` | histogram | - |

Any value on `codesentry_analyzer_errors_total` means the run exited 3 and its
report is incomplete. That is the one series worth alerting on.

The file is in Prometheus text exposition format, so a node exporter textfile
collector can read it directly from a directory, or a CI job can upload it as an
artifact. There is no scrape endpoint; see
[ADR 0004](adr/0004-metrics-as-a-dump-not-an-endpoint.md).

## Rollback

There is no running system to roll back, so this is about pinned versions.

1. **Pin the previous tag.** In a workflow, change
   `nathaniel-gordon/codesentry@v0.3.0` back. In pre-commit, change `rev:` and
   run `pre-commit clean`. With the image, deploy the previous tag.
2. **Clear the cache** if the version you rolled back from bumped the schema:
   the older build refuses to open a newer database (exit 3, `cache:` message).
   `codesentry cache . --clear`, or delete `.codesentry-cache/`.
3. **Nothing else needs undoing.** The tool writes reports and a cache. It does
   not modify the reviewed tree, does not migrate anything outside its own cache
   file, and holds no state a rollback could strand.

If the problem is a single noisy rule rather than a bad build, prefer
`--ignore <rule>` or a baseline file over rolling back the whole analyzer:

```bash
codesentry baseline src/ --output codesentry-baseline.json
codesentry review src/ --baseline codesentry-baseline.json
```

## Troubleshooting

**Exit 3 with "N file(s) could not be analyzed".** An analyzer pass raised on a
file. The report is incomplete and no gate decision from it is trustworthy. The
failing paths are on stderr and in the JSON `errors` array; re-run with
`--log-level debug` for the exception class. Please open an issue with the file.

**Exit 2, `config: unknown key(s) in [tool.codesentry]`.** A typo in
`pyproject.toml`. Unknown keys are errors on purpose - a silently ignored typo
means a rule you think is off is still firing. The message lists the known keys.

**Exit 2, `input: path escapes the review root`.** Something asked for a path
outside the tree being reviewed. If it came from a `--diff` file, the diff names
files that are not in the checkout, which the patch path drops with a log line at
`info`.

**Exit 3, `cache: cache was written by a newer codesentry`.** Exactly what it
says. `--clear-cache`, or point `--cache-path` somewhere else.

**Exit 3, `cache: cannot open cache: file is not a database`.** `--cache-path` or
`CODESENTRY_CACHE` points at something that is not a SQLite file.

**Every run is a cold run.** Check `cache=Nh/Mm` in the summary or the
`codesentry_cache_events_total` counter. Common causes: the cache directory is
not persisted between CI jobs; `--no-cache` is set; the config changed, which
invalidates by design; or the tool was upgraded.

**Churn says `static-proxy` when the tree is a git repository.** Either git is
not on PATH (`codesentry health` reports it as `skipped`), or the checkout is
shallow - `actions/checkout` defaults to `fetch-depth: 1`, which has no history
to read. Inside the container it can also be git refusing a repository owned by
another uid; the image sets `safe.directory` for that, but a differently
configured runner may not.

**The report is empty and exit is 0.** Check the settings block in the JSON: a
`--select` on one rule, or a pack restriction, disables everything else.
`codesentry rules` prints what is available.

**SARIF upload rejected by code scanning.** The uploaded file must be the one the
run wrote - `--format sarif --out <dir>` writes `<stem>.sarif` in that directory,
and the stem defaults to the subcommand's name (`review.sarif`).
