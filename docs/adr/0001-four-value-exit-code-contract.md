# 1. A four-value exit-code contract, and analyzer failures that cannot hide

- Status: accepted
- Date: 2026-08-30

## Context

codesentry is used from places that read exit codes and nothing else: a
pre-commit hook, a GitHub Action step, a `Makefile` target. Those callers have to
distinguish "your code has problems" from "you invoked me wrong" from "I broke",
and they cannot do it by parsing text that changes between versions.

The original CLI returned 0 or 1, and the agent loop caught every exception from
an analyzer pass and turned it into a line in a trace string. A rule that raised
on some AST shape therefore produced a run that said "no findings" and exited 0.

## Problem

A static analyzer that reports a clean result after crashing is worse than no
analyzer at all, because a gate built on it is now silently open. The failure has
to be visible in every output format and it has to reach the shell.

## Options considered

1. **Keep 0/1 and print a warning.** Cheapest. Rejected: nothing in CI reads
   warnings, and the gate stays green.
2. **Exit 1 for both findings and internal failures.** Rejected: it makes a
   broken install indistinguishable from a repository with a genuine finding,
   which is exactly the distinction the caller needs.
3. **Exit non-zero on any stderr output.** Rejected: logs go to stderr by design
   so that report output on stdout stays pipeable.
4. **A typed error taxonomy mapped onto four exit codes**, with analyzer failures
   collected rather than raised, and forced into the exit code at the end.

## Decision

Option 4. `reviewer/errors.py` defines `CodeSentryError` and six subclasses, each
carrying a stable slug and one of four exit codes:

| code | meaning | classes |
|---|---|---|
| 0 | clean run, no gate tripped | - |
| 1 | a gate failed | - (a policy outcome, not an error) |
| 2 | usage, configuration or input | `UsageError`, `ConfigError`, `InputError`, `ToolInputError` |
| 3 | the tool itself failed | `AnalysisError`, `CacheError` |

`ReviewSession.analyze_file` records an `AnalysisError` on `session.errors` and
re-raises. The batch walk and the agent loop both catch it and keep going, but
the error stays on the session, so `ReviewResult.ok` is false, the JSON carries
`ok: false` and an `errors` array, the SARIF sets
`invocations[0].executionSuccessful = false`, the markdown flags it, stderr lists
the failed files, and the process exits 3.

## Reasoning

The gate ("your code has a critical finding") and the failure ("I could not
analyze three files") are different events with different owners. Collapsing them
into one code means the person who fixes the finding and the person who fixes the
tool get the same signal.

Collecting rather than aborting matters too: one unparseable file in a large tree
should still produce a report for the rest, but it must not produce a *clean*
report.

## Trade-offs

- A run that finds critical defects *and* fails on one file exits 3, not 1. The
  internal failure wins because the result is incomplete and no gate decision
  taken on it is trustworthy.
- Four codes is more surface to keep stable. Changing what a code means is now a
  breaking change for every hook that consumes it.
- `--fail-on-severity` returning 1 rather than raising means the gate is a policy
  decision expressed in the CLI layer, not an exception. That is deliberate but
  it does split "how the run ends" across two mechanisms.

## Consequences

- The codes are documented in the CLI epilog, the README and this file, and they
  are covered by tests that assert the number a shell actually receives
  (`tests/test_integration.py`).
- Every new failure path must pick a class from the taxonomy. Raising a bare
  `ValueError` out of a command is a bug, because it becomes a traceback and an
  exit code Python chose rather than one this contract defines.
