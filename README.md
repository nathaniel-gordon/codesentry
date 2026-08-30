# codesentry

An AST-based static analyzer for Python. Thirty rules across four packs, scored
against a corpus with planted defects on one side and adversarial benign code on
the other, so the detection numbers below are measurements rather than claims.
Output is markdown, JSON or SARIF 2.1.0; results are cached per file so a warm
run does not re-parse the tree.

This is a reference implementation and a demo. It is not deployed anywhere,
there is no hosted service, and nobody is running it in production.

## Install

```bash
pip install -e .          # provides the `codesentry` console script
pip install -e ".[dev]"   # plus pytest, pytest-cov, ruff and mypy
```

Python 3.11 or newer. No runtime dependencies outside the standard library; the
optional LLM planner needs `anthropic`, which is an extra.

## Use

```bash
codesentry review src/ tests/            # analyze files or directories
codesentry review src/ --format sarif    # SARIF 2.1.0 for GitHub code scanning
codesentry review src/ --stdout --format json
codesentry diff --base old/ --head new/  # only the lines two snapshots differ on
codesentry patch . --diff change.diff    # only the lines a unified diff touches
codesentry rules                         # the rule table and its packs
codesentry metrics src/                  # complexity and coupling
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
listed in the JSON (`ok: false`, `errors: [...]`), flagged in the markdown, set
as `executionSuccessful: false` in the SARIF, and forces exit 3.

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

## Measured detection

Numbers below come from `codesentry eval` on the generated corpus. Reproduce
them with that exact command; nothing else in this README is a number.

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
predicts nothing about a real codebase.

## Incremental analysis

Results are cached in SQLite, keyed on `(path, sha256 of contents, sha256 of the
effective config, analyzer version)`. Editing a file, changing a threshold,
disabling a rule or upgrading the tool each invalidate exactly what they should.
Entries are stored as JSON, never pickle.

Measured here on CPython 3.14's stdlib `asyncio` package (35 files), three runs
each, Windows 10:

```
$ codesentry review <python>/Lib/asyncio --cache-path bench.db --quiet
cold  2072 / 2132 / 2138 ms
warm   649 /  656 /  676 ms
```

About 220 ms of each figure is interpreter start-up, measured with
`python -c "pass"` on the same machine. `--no-cache` bypasses the cache,
`--clear-cache` deletes it, and `codesentry cache <path>` reports on it.

## Suppression

For adopting the tool on a repository that already has findings:

```python
value = eval(expr)              # codesentry: ignore[eval-exec]
value = eval(expr)              # codesentry: ignore
# codesentry: ignore-file[long-line]
```

A pragma applies to its own line or the line below it. Additionally:

```bash
codesentry baseline src/ --output codesentry-baseline.json
codesentry review src/ --baseline codesentry-baseline.json
```

Only findings not in the baseline are reported, so an existing repository can
adopt the tool without a wall of pre-existing noise.

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

`--no-config` ignores the file entirely.

## Pre-commit hook

```yaml
repos:
  - repo: https://github.com/nathaniel-gordon/codesentry
    rev: v0.3.0
    hooks:
      - id: codesentry
```

The hook runs `codesentry review` over the staged files pre-commit passes it and
exits 1 on any finding at or above `high`. It prints nothing when it passes.

Verified here by running the hook's exact command against a scratch directory of
two files, one clean and one containing `eval()`:

```
$ codesentry review a.py --quiet --stdout --format json --fail-on-severity high
$ echo $?
0
$ codesentry review a.py b.py --quiet --stdout --format json --fail-on-severity high
FAIL: 1 finding(s) at or above high
{ ... }
$ echo $?
1
```

`pre-commit try-repo` itself has **not** been run here - pre-commit is not
installed in this environment, so what is verified is the command contract and
the installability of the package, not pre-commit's own venv bootstrap.

## GitHub Action

`action.yml` is a composite action that installs the package, runs the analyzer
and uploads the SARIF to code scanning:

```yaml
- uses: nathaniel-gordon/codesentry@v0.3.0
  with:
    paths: src
    fail-on-severity: high
```

`.github/workflows/ci.yml` runs the tests, ruff, mypy and the demo on three
Python versions, then analyzes this repository with itself and uploads the
result. **Neither has run anywhere yet** - nothing in this repository has been
pushed, so there is no green build to point at. The YAML parses; that is all
that has been checked.

## How it works

```
paths ──> ReviewSession ──> per-file: cache lookup, else parse + 4 AST passes
                        ──> cross-file: structural clone detection
                        ──> non-Python: bounded regex scan for credentials
                        ──> suppression (pragmas, baseline)
                        ──> ranking (severity x local complexity x churn)
                        ──> reporters: markdown | JSON | SARIF
```

Four passes run over one parsed module - security, correctness, complexity,
maintainability - sharing a parent map and a function list built once. Rules are
implemented against the AST, not by matching text, except the two that are
genuinely textual (line length, TODO markers).

Churn comes from `git log --numstat` where the target is a git repository, falls
back to diff line counts in diff mode, and otherwise to a documented static
structural proxy. Which one was used is printed and recorded in every report.

An optional agent loop (`--mode agent`) drives the same tools through a
plan/act/observe policy, with a Claude planner when `--planner llm` and
`ANTHROPIC_API_KEY` are both present. It is a demonstration, not the default
path, and it produces the same findings as the direct path - there is a test
asserting exactly that.

## Development

```bash
python -m pytest tests -q --cov=reviewer   # 137 tests, 90% line coverage, floor 75%
python -m ruff check reviewer tests        # clean
python -m mypy reviewer                    # clean
codesentry review reviewer                 # the tool on itself
```

The self-review is not decorative: CI gates it at `--fail-on-severity high`. It
currently reports 30 medium and low findings on this repository's own code, most
of them `high-complexity` on the analyzer's AST dispatch functions. Those are
long `isinstance` chains; splitting them to satisfy the metric would make them
harder to read, so they stand and the tool reports them.

## Limitations

- **Python only.** Nothing here understands another language.
- **Heuristic, not dataflow.** No taint tracking, no interprocedural analysis,
  no type inference, no symbolic execution. A rule fires on the shape of an AST
  node and its immediate surroundings.
- **`hardcoded-secret` and `sql-injection` are still heuristics**, tightened
  with an entropy floor, a placeholder list and a name-suffix allowlist, and
  measured against the negative corpus above. They will still be wrong on code
  the corpus does not resemble.
- **Detection is measured on one small synthetic corpus.** See the caveats under
  Measured detection.
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
- **No CI run, no deployment, no users.** Nothing here has been pushed.

## License

MIT. See `LICENSE`.

---

- **Author**: Nathaniel Gordon
- **GitHub**: [github.com/nathaniel-gordon](https://github.com/nathaniel-gordon)
- **Email**: nathanielgordon346@gmail.com
