<!-- Keep this short. Delete anything that does not apply. -->

## What changed

## Why

<!-- The constraint, the bug's cause, or the tradeoff. Not a list of the diff. -->

## Checks

- [ ] `python -m pytest tests -q --cov=reviewer`
- [ ] `python -m ruff check reviewer tests`
- [ ] `python -m mypy reviewer`
- [ ] `codesentry review reviewer --fail-on-severity high`

## If this changes rule behaviour

- [ ] A planted defect exists in `datagen.py` for every rule touched
- [ ] A look-alike exists in `negatives.py`
- [ ] `RULE_REVISION` in `cache.py` is bumped so stale cache entries are invalidated
- [ ] `codesentry eval` was run; per-rule precision and recall are below

## Numbers

<!-- Any figure quoted here needs the command that produced it. -->
