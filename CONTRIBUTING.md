# Contributing

Thanks for looking. This is a small single-maintainer project, so the most
useful contributions are precise ones: a failing case for a rule, a false
positive with the source that triggers it, or a rule whose ground truth is
missing from the corpus.

## Setup

```bash
git clone https://github.com/nathaniel-gordon/codesentry
cd codesentry
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Python 3.11 or newer. There are no runtime dependencies outside the standard
library, and there should not be any: the `dev` extra is pytest, pytest-cov,
ruff and mypy, and the optional `llm` extra is `anthropic` for the agent
planner. A pull request that adds a runtime dependency needs to argue for it.

## The checks

Everything CI runs, you can run:

```bash
python -m pytest tests -q --cov=reviewer --cov-report=term
python -m ruff check reviewer tests
python -m mypy reviewer
codesentry review reviewer --fail-on-severity high    # the tool on itself
codesentry health --json                              # readiness probe
docker build -t codesentry:dev .
```

Coverage has a floor of 75% (`[tool.coverage.report] fail_under`), and the suite
sits well above it. Do not lower the floor to make a change pass.

The self-review is a gate in the CI workflow. If your change makes the analyzer
report a new `high` or `critical` finding on this repository's own code, fix the
code rather than the gate.

## Architecture

```
reviewer/
  __main__.py     CLI: argument plumbing, the exit-code contract, output
  errors.py       the error taxonomy the exit codes are derived from
  logging_setup.py  structured logging and the per-run correlation id
  pipeline.py     review_repo / review_diff / review_patch - the shared entry points
  diffing.py      file discovery and unified-diff parsing
  scan.py         the direct execution path: analyze, clone-detect, secret-scan
  agent.py / agent_core.py   the optional plan/act/observe loop over the same tools
  llm.py          the optional Claude planner behind --planner llm
  review.py       ReviewSession: loading, per-file analysis, ranking, health
  analyzers.py    the rule table and the four AST passes
  metrics.py      complexity/size measurements of the code being reviewed
  telemetry.py    counters and latency histograms for the run itself
  cache.py        the SQLite incremental cache and its migrations
  config.py       [tool.codesentry] plus command-line overrides
  suppression.py  ignore pragmas and baseline files
  duplication.py  structural clone detection
  churn.py        change-proneness, from git history where available
  textscan.py     the bounded regex pass over non-Python files
  health.py       liveness and readiness probes
  report.py / sarif.py / tables.py    the three output formats
  datagen.py / negatives.py / evaluation.py   the corpus and its scoring
```

Two things are load-bearing and easy to break:

**The exit-code contract.** 0 clean, 1 a gate failed, 2 usage/config/input, 3 the
tool itself failed. Anything that could make an analyzer failure look like a
clean run is a bug, however small. `AnalysisError` is collected, reported in
every format, and forces exit 3.

**Everything an agent tool can be called with is untrusted.** Paths are
contained under the review root, severities and categories are validated against
their vocabularies, and search patterns are length-bounded and rejected for
catastrophic backtracking shapes. `tests/test_hardening.py` and
`tests/test_security_regressions.py` exist to keep that true.

## Adding a rule

1. Add a `RuleSpec` to `RULES` in `analyzers.py` with a severity, a category and
   a `why` that explains the consequence, not the mechanics. The pack is derived
   from the category.
2. Implement the check in the pass that owns that category.
3. Plant a defect for it in `datagen.py` so the corpus has ground truth. A test
   fails if any rule has no planted defect.
4. Add a look-alike to `negatives.py` - the shape that *resembles* the defect but
   is correct. Precision is measured on those files, so a rule with no negative
   is a rule nobody can tell is over-firing.
5. Bump `RULE_REVISION` in `cache.py`. Behaviour changed, so every cached entry
   made with the old behaviour has to be invalidated.
6. Run `codesentry eval` and check the new rule's precision and recall.

## Coding standards

- Ruff with `E,F,I,B,UP,C4,SIM,RUF` and a 100 character line limit
  (`pyproject.toml` has the exceptions and why they are there).
- mypy over `reviewer/`, clean.
- Every public function has a docstring saying what it returns, not what it does
  line by line.
- Comments explain *why*. If a comment restates the code, delete it.
- Standard library only in `reviewer/`.
- New behaviour comes with a test. New *hardening* comes with a test named after
  the thing it prevents.

## Commits and pull requests

Short imperative subjects, roughly 50 characters, lowercase after any
conventional prefix. A body only when the reason is not obvious from the
subject, and then it explains the constraint or the cause rather than listing
the diff.

```
add sqlite event store with WAL
fix double-counting when a card replays mid-window
readme: cut the latency claim
```

Before opening a pull request, run the checks above. Say in the description what
you measured and with which command; numbers without a command that produced
them will be asked about.

## Reporting a false positive

The most valuable issue this project can receive. Include the smallest source
file that triggers it, the rule id, and the command you ran. If it is a real
false positive it becomes a new entry in `negatives.py`, and precision is
measured against it from then on.

Security issues go to `SECURITY.md` instead, not to the issue tracker.
