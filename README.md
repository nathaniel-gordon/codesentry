# codesentry

An AST-based static analyzer for Python. Thirty rules across four packs, scored
against a corpus with planted defects on one side and adversarial benign code on
the other, so the detection numbers below are measurements rather than claims.
Output is markdown, JSON or SARIF 2.1.0; results are cached per file so a warm
run does not re-parse the tree.

This is a reference implementation and a demo. It is not deployed anywhere, there
is no hosted service, nothing has been pushed, and nobody is running it in
production.

## What it does

- Finds defects in Python source from the AST: 30 rules over security,
  correctness, complexity and maintainability.
- Ranks them by risk - severity multiplied by the complexity of the code they sit
  in and by how often that file changes - so the top of the report is the part
  worth reading first.
- Scores a repository 0-100 on finding density, complexity, duplication and
  documentation coverage.
- Reviews **only what changed**, from two directory snapshots (`diff`) or a
  unified diff file (`patch`), so a pull request is not judged on pre-existing
  code.
- Detects copy-pasted logic across files structurally, with identifiers and
  literals erased.
- Searches non-Python config files for credentials, bounded in every dimension.
- Caches per-file results in SQLite so a warm run skips work that cannot have
  changed.
- Emits SARIF 2.1.0 for GitHub code scanning, markdown for humans and JSON for
  everything else.
- Gates a build on severity or on the health score, with an exit-code contract
  a shell script can act on.
- Suppresses known findings through inline pragmas or a baseline file, so an
  existing repository can adopt it without a wall of noise.

## Architecture

```
                    codesentry review|diff|patch|metrics|baseline|cache|health|demo|eval
                                              __main__.py
                                    argument plumbing, gates, exit codes
                                                   |
                            config.py  <-- [tool.codesentry] + CLI overrides
                                                   |
                                              pipeline.py
                              review_repo / review_diff / review_patch
                                       |                       |
                          mode=direct  |                       |  mode=agent
                              scan.py  |                       |  agent.py + agent_core.py
                                       \                       /   (plan/act/observe,
                                        \                     /     optional LLM planner)
                                         v                   v
                                          ReviewSession  (review.py)
                                          ---------------------------
   per file:  cache.py lookup ---- hit ---> findings + metrics + clone blocks
                   | miss
                   v
             analyzers.py  four passes over one shared AST
                security | correctness | complexity | maintainability
                   +  metrics.py    complexity, nesting, params, docstrings
                   +  duplication.py  structural token blocks
                                          |
   cross file:  duplication.py  clone pairs from the blocks of every file
   non-Python:  textscan.py     bounded regex scan for credentials
                                          |
                                          v
                    suppression.py   pragmas + baseline
                    churn.py         git log --numstat, else diff, else static proxy
                    risk ranking     severity x local complexity x churn
                    health score     density, complexity, duplication, docs
                                          |
                    report.py  ->  markdown + JSON
                    sarif.py   ->  SARIF 2.1.0
                    telemetry.py -> counters + latency histograms (--metrics-out)

  errors.py         typed failures mapped onto four exit codes
  logging_setup.py  structured logs with one run id per run
  health.py         liveness / readiness probes
  datagen.py + negatives.py + evaluation.py   the corpus and its scoring
```

Four passes run over one parsed module, sharing a parent map and a function list
built once. Rules are implemented against the AST, not by matching text, except
the two that are genuinely textual (line length, TODO markers).

Both execution modes write into the same `ReviewSession`, so they produce the
same shaped result and share one risk model. There is a test asserting agent mode
finds exactly what direct mode finds.

## Stack

Python 3.11+ and the standard library. `ast`, `sqlite3`, `argparse`,
`subprocess`, `hashlib`, `logging`, `tomllib`, `dataclasses`, `re`.

No runtime dependencies. `anthropic` is an optional extra used only by
`--mode agent --planner llm`; nothing else in the tool touches the network.
Development uses pytest, pytest-cov, ruff and mypy.

## Quick start

```bash
pip install -e .          # provides the `codesentry` console script
pip install -e ".[dev]"   # plus pytest, pytest-cov, ruff and mypy
```

```bash
codesentry review src/ tests/            # analyze files or directories
codesentry review src/ --format sarif    # SARIF 2.1.0 for GitHub code scanning
codesentry review src/ --stdout --format json
codesentry diff --base old/ --head new/  # only the lines two snapshots differ on
codesentry patch . --diff change.diff    # only the lines a unified diff touches
codesentry rules                         # the rule table and its packs
codesentry metrics src/                  # complexity and coupling
codesentry health                        # readiness probe
codesentry demo                          # generate the corpus, review it, score it
codesentry eval                          # per-rule precision and recall
```

### Exit codes

| code | meaning |
|---|---|
| 0 | clean run, no gate tripped |
| 1 | a gate failed (`--fail-on-severity`, `--fail-under`) |
| 2 | usage, configuration or input problem |
| 3 | internal failure, including any file that could not be analyzed |

Code 3 exists because the worst thing a linter can do is report "no findings"
after crashing. Any per-file analyzer failure is collected, printed to stderr,
listed in the JSON (`ok: false`, `errors: [...]`), flagged in the markdown, set as
`executionSuccessful: false` in the SARIF, and forces exit 3. The reasoning is in
[ADR 0001](docs/adr/0001-four-value-exit-code-contract.md).

## Rules

Four packs, thirty rules, one flat table in `reviewer/analyzers.py` carrying each
rule's severity, category and a paragraph on why it matters. `codesentry rules`
prints the whole table; `codesentry rules --json` emits it for tooling.

| pack | rules |
|---|---|
| security | 8 |
| correctness | 10 |
| complexity | 5 |
| maintainability | 7 |

Selection: `--pack security`, `--select eval-exec`, `--ignore long-line`. All
three are repeatable, and `--select` is exclusive: naming any rule runs only the
rules you named.

## Configuration

`[tool.codesentry]` in the nearest `pyproject.toml`. Command-line flags win over
the file; the file wins over the built-in defaults. Unknown keys and unknown rule
ids are errors, not warnings, because a typo would otherwise silently disable
nothing.

```toml
[tool.codesentry]
packs = ["security", "correctness", "complexity", "maintainability"]
max-complexity = 12
max-nesting = 5
ignore = []
exclude = ["output", "build", "dist"]
```

`--no-config` ignores the file entirely. Every report records the settings it
actually ran with, so a report can be reproduced from itself rather than from
whatever the config file says today.

### Suppression

```python
value = eval(expr)              # codesentry: ignore[eval-exec]
value = eval(expr)              # codesentry: ignore
# codesentry: ignore-file[long-line]
```

A pragma applies to its own line or the line below it. For adopting the tool on a
repository that already has findings:

```bash
codesentry baseline src/ --output codesentry-baseline.json
codesentry review src/ --baseline codesentry-baseline.json
```

Only findings not in the baseline are reported.

## Evaluation

Numbers below come from the commands shown, run on this machine (Windows 10,
Python 3.14.6). Nothing else in this README is a number.

### Detection

```
$ codesentry eval
totals: tp=34 fp=0 fn=0  precision=1.00  recall=1.00
corpus: 21 files, 34 planted defects, 14 benign files
        (false positives are counted on those only)
```

Every one of the thirty rules has at least one planted defect, and a test fails
if that stops being true. Recall is measured at the exact `file:line:rule`, not
per file.

**What that number is not.** It is one synthetic corpus of 21 small files that
this repository generates itself. False positives are counted only on the 14
files written to be benign, because those are the only places a finding is
provably wrong. Those files are deliberately adversarial rather than easy - the
`API_KEY_HEADER = "X-Api-Key"` constant, the pairwise `range(len(xs) - 1)` loop,
`ast.literal_eval`, `hashlib.md5(..., usedforsecurity=False)`, functions sitting
exactly on the complexity ceiling - but fourteen files is fourteen files. This
predicts nothing about a real codebase. See
[ADR 0006](docs/adr/0006-measure-precision-on-an-adversarial-negative-corpus.md).

### Incremental analysis

Results are cached in SQLite, keyed on `(path, sha256 of contents, sha256 of the
effective config, analyzer version)`. Editing a file, changing a threshold,
disabling a rule or upgrading the tool each invalidate exactly what they should.
Entries are stored as JSON, never pickle.

Measured on CPython 3.14's stdlib `asyncio` package (35 files), three runs each,
wall clock around the whole subprocess:

```
$ codesentry review <python>/Lib/asyncio --cache-path bench.db --quiet --stdout --format json
cold  2035 / 2042 / 2093 ms      (cache deleted before each run)
warm   579 /  586 /  580 ms
```

About 100 ms of each figure is interpreter start-up, measured as
`python -c "pass"` under the same subprocess harness (103 / 99 / 96 ms).
`--no-cache` bypasses the cache, `--clear-cache` deletes it, and
`codesentry cache <path>` reports on it.

### The tool on itself

```
$ codesentry review reviewer --no-cache
engine=direct  files=27  sloc=5271  churn=git-log  findings=32  cache=0h/27m
health score: 93.8/100 (grade A)
severity  count
--------  -----
critical  0
high      0
medium    22
low       10
```

By rule: `high-complexity` 13, `too-many-params` 6, `long-function` 4,
`deep-nesting` 3, `duplicate-block` 2, `long-line` 2, `todo-marker` 2.

CI gates this at `--fail-on-severity high`, which passes because nothing here
reaches high. Most of the remainder is `high-complexity` on the analyzer's own
AST dispatch functions - long `isinstance` chains where splitting them to satisfy
the metric would make them harder to read. They stand, and the tool reports them.

## Local development

```bash
git clone https://github.com/nathaniel-gordon/codesentry
cd codesentry
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Everything CI runs:

```bash
python -m pytest tests -q --cov=reviewer --cov-report=term
python -m ruff check reviewer tests
python -m mypy reviewer
codesentry review reviewer --fail-on-severity high
codesentry health --json
docker build -t codesentry:dev .
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the module map, how to add a rule, and
the commit conventions.

## Testing

```
$ python -m pytest tests --cov=reviewer --cov-report=term
TOTAL                        2950    201    904     95    92%
Required test coverage of 75.0% reached. Total coverage: 91.70%
410 passed, 4 warnings in 15.05s
```

410 tests, 91.7% combined line and branch coverage, floor 75%
(`[tool.coverage.report] fail_under`). 149 of those are parametrized cases in
`test_invariants.py`, so the count is not 410 independent scenarios - it is
seventeen files' worth of behaviour, some of it swept over generated inputs.

| file | what it covers |
|---|---|
| `test_corpus.py` | every planted defect is found, no finding on the benign corpus |
| `test_precision_security.py` | the two heuristic rules, positive and negative cases |
| `test_resources.py` | the unclosed-resource rule's escape hatches |
| `test_cli.py` | every subcommand, the gates, the exit codes |
| `test_integration.py` | the same through a real subprocess, plus the metrics dump |
| `test_invariants.py` | properties over generated modules: ranking, scoring, determinism |
| `test_cache.py` | hits, misses, and every invalidation dimension |
| `test_migrations.py` | a v1 database carried forward, WAL, constraints, rollback |
| `test_hardening.py` | path containment, tool-argument validation, regex bounds |
| `test_security_regressions.py` | one test per fixed vulnerability (see below) |
| `test_suppression_config.py` | pragmas, baselines, packs, config precedence |
| `test_sarif.py` | the SARIF envelope, rule index, fingerprints |
| `test_telemetry.py` | counters, histogram buckets, both dump formats |
| `test_health.py` | liveness and readiness, including the failures they catch |
| `test_logging.py` | the JSON record shape and the run id |
| `test_agent.py` | agent mode finds what direct mode finds |
| `test_churn.py` | the three churn sources, against a real throwaway repository |

Only Python 3.14.6 has actually been exercised here. The CI matrix declares
3.11 through 3.14, and **that matrix has never run** - nothing has been pushed.

## Observability

Structured logs on stderr, one JSON object per line, every record carrying the
same run id:

```bash
codesentry review src/ --log-level info --log-format json
```

```json
{"ts": "2026-08-30T22:27:46", "level": "info", "run_id": "2e6db691c4b4", "logger": "codesentry.scan", "event": "review finished", "files": 27, "findings": 32, "errors": 0, "elapsed_ms": 114.7, "cache_hits": 27, "cache_misses": 0}
```

A fixed key list (`api_key`, `token`, `password`, `secret`, `source`, ...) is
redacted to `***` in every record, in both formats.

Counters and latency histograms are dumped at the end of a run, in Prometheus
text exposition format or JSON:

```bash
codesentry review src/ --metrics-out reports/run.prom
codesentry review src/ --metrics-out reports/run.json
```

The series that actually emit: `codesentry_files_analyzed_total`,
`codesentry_cache_events_total`, `codesentry_findings_total`,
`codesentry_analyzer_errors_total`, `codesentry_suppressed_findings_total`,
`codesentry_file_analysis_duration_ms`, `codesentry_phase_duration_ms` and
`codesentry_run_duration_ms`. Any value on the errors counter means the run
exited 3 and its report is incomplete.

There is no scrape endpoint. This is a batch process that exits in under two
seconds; a scraper would arrive to find nothing. The reasoning, and what would
change that, is in
[ADR 0004](docs/adr/0004-metrics-as-a-dump-not-an-endpoint.md).

Health:

```bash
codesentry health --probe liveness     # install integrity, no filesystem
codesentry health --json               # readiness: config, cache, output dir, git
```

Exit 0 when every check passes, 3 when any fails. The container HEALTHCHECK runs
the liveness probe.

## Security

The reviewed tree is untrusted input - that is the tool's whole job - and so is
anything an LLM planner produces under `--mode agent --planner llm`. What that
means concretely:

- every path is contained under the review root, whether it came from a CLI
  argument, a diff header, a config file or a model tool call;
- `git` is invoked with `core.fsmonitor`, `core.pager` and `core.hooksPath`
  pinned on the command line, so a hostile `.git/config` cannot name a program
  for git to run;
- the result cache stores JSON and never pickle, and a row that will not decode
  is dropped and re-analyzed rather than trusted;
- the regex pass over non-Python files caps pattern length, refuses nested
  quantifiers, and limits file size, line length, file count, match count and
  wall-clock time;
- log records redact a fixed key list, and the config scan reports the *name* of
  a credential key and its location, never the value.

Each of those has a regression test named after what it prevents, in
`tests/test_hardening.py` and `tests/test_security_regressions.py`. There has
been no external audit, no fuzzing campaign and no penetration test. Reporting:
[SECURITY.md](SECURITY.md).

## Deployment

Nothing is deployed. [docs/deployment.md](docs/deployment.md) documents the
intended target - the analyzer running as a step in the CI job that already
checked out the code - with prerequisites, environment variables, the cache
migration story, build, health checks, rollback and troubleshooting.

```bash
docker build -t codesentry:0.3.0 .
docker run --rm -v "$PWD:/work/repo:ro" codesentry:0.3.0 review repo --fail-on-severity high
```

The image is two-stage, runs as a non-root user, and its HEALTHCHECK runs the
liveness probe. Built and run here; `docker images` reports 332MB.

### Pre-commit hook

```yaml
repos:
  - repo: https://github.com/nathaniel-gordon/codesentry
    rev: v0.3.0
    hooks:
      - id: codesentry
```

The hook runs `codesentry review` over the staged files pre-commit passes it and
exits 1 on any finding at or above `high`. It prints nothing when it passes.
`pre-commit try-repo` has **not** been run here - pre-commit is not installed in
this environment, so what is verified is the command contract and the
installability of the package, not pre-commit's own venv bootstrap.

### GitHub Action

`action.yml` is a composite action that installs the package, runs the analyzer
and uploads the SARIF to code scanning. `.github/workflows/ci.yml` runs lint,
type check, tests with coverage on four Python versions, the demo and evaluation,
a docker build, and this repository analyzed by itself. **Neither has run
anywhere** - nothing has been pushed, so there is no green build to point at. The
YAML parses and every command in it was run locally first.

## Limitations

- **Python only.** Nothing here understands another language.
- **Heuristic, not dataflow.** No taint tracking, no interprocedural analysis, no
  type inference, no symbolic execution. A rule fires on the shape of an AST node
  and its immediate surroundings.
- **`hardcoded-secret` and `sql-injection` are still heuristics**, tightened with
  an entropy floor, a placeholder list and a name-suffix allowlist, and measured
  against the negative corpus. They will still be wrong on code the corpus does
  not resemble.
- **Detection is measured on one small synthetic corpus** that this repository
  generates itself. See the caveats under Evaluation.
- **The regex scan over config files has a residual bound.** The deadline is
  checked between lines and cannot interrupt a single `re.search`, so a
  pathological pattern on one very long line can overrun it. The line-length cap
  is what keeps that finite.
- **Clone detection is structural and intra-run.** Identifiers and literals are
  erased before shingling, so it finds copy-paste, not semantic duplication, and
  only within the files analyzed in that run.
- **The health score is not scale-invariant.** It is a density measure; use
  `--fail-on-severity` as a gate, not `--fail-under`, on anything smaller than a
  whole repository.
- **Metrics do not aggregate across runs.** Each dump describes one process.
- **The cache grows until pruned.** `codesentry cache --prune KEEP` exists;
  nothing calls it automatically.
- **Only Python 3.14 has been exercised.** The declared floor is 3.11 and the CI
  matrix covers 3.11-3.14, but that matrix has never run.
- **No CI run, no deployment, no users, no published package.** Nothing here has
  been pushed.

## Roadmap

Nothing here is committed to or scheduled; it is what the current design points
at next.

- Per-rule autofix suggestions for the mechanical rules (`unused-import`,
  `long-line`), emitted as SARIF `fixes` so a forge can offer them.
- A real corpus check: run against a handful of large open-source repositories
  and hand-label a sample, to put a number on precision that the synthetic corpus
  cannot.
- Cross-file reasoning for the two rules that most want it - unused public API
  and duplicated logic - which currently stop at the module boundary.
- Cache pruning on open, so long-lived CI caches stay bounded without a flag.
- Publish the wheel and the image, which is what would let the deployment
  document stop saying "not published".

## Contributing

Issues and pull requests are welcome. A false positive with the source file that
triggers it is the single most useful thing to send - it becomes an entry in the
negative corpus and precision is measured against it from then on.
[CONTRIBUTING.md](CONTRIBUTING.md) has setup, the checks, the module map, how to
add a rule, and the commit conventions.
[docs/adr/](docs/adr/) records the decisions and what they cost.

## License

MIT. See [LICENSE](LICENSE).

---

- **Author**: Nathaniel Gordon
- **GitHub**: [github.com/nathaniel-gordon](https://github.com/nathaniel-gordon)
- **Email**: nathanielgordon346@gmail.com
