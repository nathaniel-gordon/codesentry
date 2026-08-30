# Security policy

## Supported versions

| version | supported |
|---|---|
| 0.3.x | yes |
| < 0.3 | no |

This is a pre-1.0 reference implementation maintained by one person. There is no
release cadence and no backporting; fixes land on `main` and go out in the next
version.

## Reporting a vulnerability

Email **nathanielgordon346@gmail.com** with `codesentry security` in the subject.
Please do not open a public issue for anything exploitable.

Include the version (`codesentry --help` prints the program name;
`pip show codesentry` prints the version), the exact command, and the smallest
input that reproduces the problem. If it involves a repository under analysis, a
minimal directory tree is far more useful than a description of one.

There is no bug bounty. Expect an acknowledgement within a week; this is a side
project, not a staffed product, and that is the honest expectation to set.

## Threat model

codesentry reads code it does not trust. That is its whole job, so the reviewed
tree is treated as hostile input, and so is anything an LLM planner produces
under `--mode agent --planner llm`.

**In scope** - the tool being made to do something the operator did not ask for:

- reading or writing files outside the review root (path containment is enforced
  in `ReviewSession.abspath`, and every tool argument goes through it);
- executing anything from the reviewed tree - `git` is invoked with
  `core.fsmonitor`, `core.pager` and `core.hooksPath` pinned on the command line
  so a hostile `.git/config` cannot name a program for git to run;
- deserialising attacker-controlled data - the result cache stores JSON and never
  pickle, and a corrupt row is dropped and re-analyzed rather than trusted;
- unbounded work from bounded input - the regex pass over non-Python files caps
  pattern length, refuses nested quantifiers, limits file size, line length, file
  count and match count, and carries a wall-clock deadline;
- secrets reaching a place they should not - log records redact a fixed key list,
  and the config-file scan reports the *name* of a credential key and its
  location, never the value.

**Out of scope:**

- Findings the analyzer misses. It is a heuristic AST linter with no dataflow
  analysis, no taint tracking and no type inference; a missed vulnerability in
  reviewed code is a rule gap, which is an ordinary issue, not a security report.
- False positives. Also an ordinary issue - see CONTRIBUTING.md, they are welcome.
- Anything requiring the operator to run the tool against their own machine with
  flags that say what they will do (`--cache-path` pointing somewhere odd,
  `--out` overwriting a file you named).
- Denial of service through sheer repository size. The tool is a batch job with
  no admission control; point it at a smaller tree.
- The optional LLM planner sending code to Anthropic when you set
  `ANTHROPIC_API_KEY` and pass `--planner llm`. That is the documented purpose of
  the flag. Everything else runs entirely offline.

## What is verified, and how

Each hardening item above has a regression test named after what it prevents, in
`tests/test_hardening.py` and `tests/test_security_regressions.py`. They run in
CI on every push. That is the extent of the assurance: there has been no external
audit, no fuzzing campaign and no penetration test, and this software is not
deployed anywhere.
