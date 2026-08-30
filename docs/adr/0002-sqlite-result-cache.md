# 2. A SQLite result cache keyed on content, config and analyzer version

- Status: accepted
- Date: 2026-08-30

## Context

Every run re-read, re-parsed and re-analyzed every file. That is fine for a demo
over 21 generated files and wrong for the two places the tool is meant to be
used: a pre-commit hook that fires on every commit, and a CI job on a repository
where almost nothing changed since the last run.

## Problem

Reuse a previous run's per-file results without ever serving a stale one. The
answer for a file depends on more than its contents: a threshold change, a
disabled rule, or a fix to a rule's implementation all change what the analyzer
would say about a file whose bytes are identical.

## Options considered

1. **No cache.** Simple, and the status quo. Rejected on the pre-commit case.
2. **A JSON file keyed on path.** Rejected: the whole file is rewritten on every
   run, two concurrent runs corrupt it, and there is no way to expire entries.
3. **Pickle the `Finding` objects.** Rejected outright. The cache is a plain file
   in a directory the reviewed repository controls; unpickling it is arbitrary
   code execution triggered by running a linter.
4. **A content-addressed directory of JSON blobs.** Workable, but reimplements
   indexing, atomic replacement and pruning by hand.
5. **SQLite with an explicit schema and forward migrations.**

## Decision

Option 5. `reviewer/cache.py` stores one row per analyzed file, with a UNIQUE
constraint on the full cache key:

```
(path, sha256(contents), sha256(effective config), analyzer version)
```

The analyzer version is `{package version}+r{RULE_REVISION}`, so both a release
upgrade and an in-place rule fix invalidate every entry. Findings, metrics and
clone-detection token blocks are stored as JSON columns. WAL is on, three indexes
cover the lookup, and schema changes go through a numbered `_MIGRATIONS` tuple
applied one transaction per step and recorded in a `schema_version` table.
Opening a database written by a newer build is a `CacheError`, not a guess.

## Reasoning

SQLite is in the standard library, gives transactions and a real index for free,
and survives two processes touching it - which WAL makes ordinary rather than
exotic, and a pre-commit hook running while an editor plugin runs is exactly that
case.

Storing JSON rather than pickle is not a performance decision; it is the
difference between a corrupt cache being a re-analysis and a corrupt cache being
remote code execution. A row that will not decode is deleted and counted as a
miss.

Hashing the *effective* config rather than the config file means command-line
overrides participate in the key, so `--max-complexity 5` and
`--max-complexity 20` do not share entries.

## Trade-offs

- The cache grows without bound until pruned. `codesentry cache --prune KEEP`
  exists, but nothing prunes automatically.
- Storing token blocks makes rows larger than findings alone would, in exchange
  for a warm run never reparsing a file just to compare its shape during clone
  detection.
- A schema change is now a migration, with a version number and a test, rather
  than deleting a file.
- Cross-file results (clone pairs) are *not* cached; only the per-file inputs to
  them are. Clone detection re-runs every time.

## Consequences

- `RULE_REVISION` must be bumped whenever a rule's behaviour changes. The
  contributing guide and the pull request template both say so, because a
  forgotten bump means users silently get old answers.
- `tests/test_migrations.py` builds a database at schema v1 and asserts it is
  carried forward with its rows intact, which is the only way to know the
  migration path still works once nobody has a v1 database left.
