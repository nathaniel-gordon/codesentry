# 3. The agent loop is a mode, not the execution path

- Status: accepted
- Date: 2026-08-30

## Context

The tool was built around a plan/act/observe agent. Every review - including a
pre-commit hook on two staged files - constructed an agent, gave it a goal
string, and let it decide which tools to call.

Its default planner was deterministic: a hardcoded `if/elif` chain that called
`analyze_file` for each file, then `detect_duplicates`, then `search_files`, in
that order, every time. The loop also wrapped each tool call in a broad
`except Exception` that appended the exception's text to a trace string.

## Problem

Two costs with no matching benefit. The loop added an interpretation layer, a
goal string and a trace to a sequence that was fixed, and its exception handling
turned an analyzer crash into a line of prose in a report nobody parses - which
is how "no findings" could mean "the rule raised on your file".

## Options considered

1. **Delete the agent.** It is genuinely capable and is the interesting part of
   the project when a real planner is driving it. Deleting it to simplify the
   default path throws away work that does something the direct path cannot:
   choose what to look at next.
2. **Keep the loop and fix only the exception handling.** Leaves the interpretive
   layer in the pre-commit path, where nothing wants it.
3. **Make the direct sequence the default and keep the loop behind a flag.**

## Decision

Option 3. `reviewer/scan.py` holds `analyze_repo`: analyze every discovered file,
detect cross-file clones, scan non-Python files for credentials, in that order.
`review_repo(mode="direct")` is the default and builds no agent at all.
`--mode agent` runs the same tools under the planner, with `--planner llm`
selecting a Claude planner when `ANTHROPIC_API_KEY` is present and degrading to
the deterministic one when it is not - and the report records which engine
actually ran, not which was requested.

Both modes write into the same `ReviewSession`, so they produce the same shaped
result and share one risk model.

## Reasoning

An agent earns its cost when the next action depends on what the previous one
found. Reviewing a repository end to end does not have that shape: every file
gets analyzed, and the order does not matter. The agent's value here is as a
demonstration of the same capabilities under a planner, and a demonstration
should be reachable on request rather than mandatory.

Keeping one session object means the modes cannot drift. There is a test
asserting that agent mode finds exactly what direct mode finds.

## Trade-offs

- Two execution paths to maintain, and both have to be tested.
- The agent path is exercised much less, so bugs there will be found later.
- Someone reading the code has to learn that `agent.py` is not the main path,
  which is why the module docstring says so in its first paragraph.

## Consequences

- The pre-commit hook and the GitHub Action both use the direct path; neither
  constructs a planner, and neither needs credentials.
- `AnalysisError` is now recorded on the session by `analyze_file` itself, so it
  survives whichever loop is calling it - the fix outlives the mode that made it
  urgent (see ADR 0001).
