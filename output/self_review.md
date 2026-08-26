# Code Review

- **Repository**: `D:\khalid\21-code-review-agent\reviewer`
- **Mode**: full
- **Generated**: 2026-08-25 04:48 UTC
- **Files reviewed**: 14  |  **SLOC**: 2482
- **Churn signal**: static-proxy

## Health score: 86.0/100 (grade B)

| penalty | points |
|---|---|
| finding_density | 7.36 |
| complexity | 2.33 |
| duplication | 2.13 |
| documentation | 2.18 |

Average cyclomatic complexity 4.58, public-API docstring coverage 89%, weighted severity 83.0.

## Findings by severity

| severity | count |
|---|---|
| critical | 0 |
| high | 0 |
| medium | 23 |
| low | 14 |

## Findings by category

| category | count |
|---|---|
| complexity | 25 |
| maintainability | 12 |

## Top risks (severity x complexity x churn)

| risk | severity | location | rule | message |
|---|---|---|---|---|
| 16.0 | medium | `analyzers.py:669` | deep-nesting | '_check_imports' nests control flow 5 levels deep (max 4) |
| 16.0 | medium | `analyzers.py:669` | high-complexity | '_check_imports' cyclomatic complexity 25 (max 10) |
| 14.8 | medium | `analyzers.py:240` | deep-nesting | '_terminates' nests control flow 7 levels deep (max 4) |
| 14.8 | medium | `analyzers.py:240` | high-complexity | '_terminates' cyclomatic complexity 22 (max 10) |
| 13.6 | medium | `analyzers.py:338` | high-complexity | '_security_call' cyclomatic complexity 19 (max 10) |
| 12.8 | medium | `analyzers.py:553` | high-complexity | '_check_unused_and_shadowed' cyclomatic complexity 17 (max 10) |
| 12.4 | medium | `analyzers.py:481` | high-complexity | '_check_off_by_one' cyclomatic complexity 16 (max 10) |
| 9.9 | medium | `report.py:27` | high-complexity | 'render_markdown' cyclomatic complexity 25 (max 10) |
| 9.9 | medium | `report.py:27` | long-function | 'render_markdown' is 91 lines (max 60) |
| 9.6 | medium | `analyzers.py:432` | deep-nesting | 'pass_correctness' nests control flow 6 levels deep (max 4) |

## Riskiest files

| file | risk | findings | sloc | max cc |
|---|---|---|---|---|
| `analyzers.py` | 110.0 | 8 | 686 | 25 |
| `agent.py` | 40.0 | 6 | 232 | 16 |
| `report.py` | 19.8 | 2 | 120 | 25 |
| `datagen.py` | 19.1 | 5 | 469 | 4 |
| `diffing.py` | 13.6 | 2 | 133 | 14 |
| `agent_core.py` | 12.9 | 9 | 101 | 7 |
| `duplication.py` | 12.3 | 2 | 120 | 13 |
| `review.py` | 9.8 | 2 | 231 | 12 |
| `pipeline.py` | 1.2 | 1 | 54 | 3 |

## Findings


### `agent.py`

- **[MEDIUM] deep-nesting** - `agent.py:92`  
  'search_pattern' nests control flow 6 levels deep (max 4)  
  *Why it matters*: each nesting level multiplies the conditions a reader must track; deeply nested code is where inverted-condition bugs live.  
  *Fix*: invert conditions to return early, or extract the inner loop
- **[LOW] too-many-params** - `agent.py:116`  
  'record_finding' takes 9 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object
- **[MEDIUM] deep-nesting** - `agent.py:126`  
  '_candidate_files' nests control flow 5 levels deep (max 4)  
  *Why it matters*: each nesting level multiplies the conditions a reader must track; deeply nested code is where inverted-condition bugs live.  
  *Fix*: invert conditions to return early, or extract the inner loop
- **[MEDIUM] high-complexity** - `agent.py:174`  
  'deterministic_policy' cyclomatic complexity 16 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] long-function** - `agent.py:174`  
  'deterministic_policy' is 65 lines (max 60)  
  *Why it matters*: a function longer than a screen cannot be diffed or reviewed as a unit, so changes to it are approved without being understood.  
  *Fix*: split it along its comment headings into separate functions
- **[MEDIUM] high-complexity** - `agent.py:182` in `deterministic_policy()`  
  'policy' cyclomatic complexity 16 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns

### `agent_core.py`

- **[LOW] missing-docstring** - `agent_core.py:15`  
  public class 'Tool' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[LOW] missing-docstring** - `agent_core.py:21`  
  public function 'spec' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[LOW] missing-docstring** - `agent_core.py:26`  
  public class 'ToolRegistry' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[LOW] missing-docstring** - `agent_core.py:30`  
  public function 'register' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[LOW] missing-docstring** - `agent_core.py:33`  
  public function 'get' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[LOW] missing-docstring** - `agent_core.py:36`  
  public function 'catalog' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[LOW] missing-docstring** - `agent_core.py:41`  
  public class 'Step' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[LOW] missing-docstring** - `agent_core.py:67`  
  public function 'run' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[LOW] missing-docstring** - `agent_core.py:91`  
  public function 'trace_report' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises

### `analyzers.py`

- **[MEDIUM] deep-nesting** - `analyzers.py:240`  
  '_terminates' nests control flow 7 levels deep (max 4)  
  *Why it matters*: each nesting level multiplies the conditions a reader must track; deeply nested code is where inverted-condition bugs live.  
  *Fix*: invert conditions to return early, or extract the inner loop
- **[MEDIUM] high-complexity** - `analyzers.py:240`  
  '_terminates' cyclomatic complexity 22 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] high-complexity** - `analyzers.py:338`  
  '_security_call' cyclomatic complexity 19 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] deep-nesting** - `analyzers.py:432`  
  'pass_correctness' nests control flow 6 levels deep (max 4)  
  *Why it matters*: each nesting level multiplies the conditions a reader must track; deeply nested code is where inverted-condition bugs live.  
  *Fix*: invert conditions to return early, or extract the inner loop
- **[MEDIUM] high-complexity** - `analyzers.py:481`  
  '_check_off_by_one' cyclomatic complexity 16 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] high-complexity** - `analyzers.py:553`  
  '_check_unused_and_shadowed' cyclomatic complexity 17 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] deep-nesting** - `analyzers.py:669`  
  '_check_imports' nests control flow 5 levels deep (max 4)  
  *Why it matters*: each nesting level multiplies the conditions a reader must track; deeply nested code is where inverted-condition bugs live.  
  *Fix*: invert conditions to return early, or extract the inner loop
- **[MEDIUM] high-complexity** - `analyzers.py:669`  
  '_check_imports' cyclomatic complexity 25 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns

### `datagen.py`

- **[MEDIUM] long-function** - `datagen.py:191`  
  '_stock' is 78 lines (max 60)  
  *Why it matters*: a function longer than a screen cannot be diffed or reviewed as a unit, so changes to it are approved without being understood.  
  *Fix*: split it along its comment headings into separate functions
- **[MEDIUM] duplicate-block** - `datagen.py:271` in `_reporting()`  
  '_reporting' is 100% structurally identical to '_gateway' at datagen.py:89  
  *Why it matters*: copy-pasted logic means every bug must be fixed N times; in practice only the copy that was reported gets fixed.  
  *Fix*: extract the shared logic into one function and call it from both sites
- **[MEDIUM] long-function** - `datagen.py:271`  
  '_reporting' is 94 lines (max 60)  
  *Why it matters*: a function longer than a screen cannot be diffed or reviewed as a unit, so changes to it are approved without being understood.  
  *Fix*: split it along its comment headings into separate functions
- **[LOW] todo-marker** - `datagen.py:374`  
  # TODO: delete this module once the v2 exporter ships  
  *Why it matters*: a TODO in code is an issue nobody is tracking and nobody is assigned.  
  *Fix*: file an issue and link it, or delete the note
- **[LOW] todo-marker** - `datagen.py:378`  
  ("todo-marker", "# TODO:"),  
  *Why it matters*: a TODO in code is an issue nobody is tracking and nobody is assigned.  
  *Fix*: file an issue and link it, or delete the note

### `diffing.py`

- **[MEDIUM] high-complexity** - `diffing.py:84`  
  'parse_unified_diff' cyclomatic complexity 14 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] high-complexity** - `diffing.py:132`  
  'filter_findings' cyclomatic complexity 11 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns

### `duplication.py`

- **[MEDIUM] deep-nesting** - `duplication.py:74`  
  'extract_blocks' nests control flow 5 levels deep (max 4)  
  *Why it matters*: each nesting level multiplies the conditions a reader must track; deeply nested code is where inverted-condition bugs live.  
  *Fix*: invert conditions to return early, or extract the inner loop
- **[MEDIUM] high-complexity** - `duplication.py:98`  
  'find_duplicates' cyclomatic complexity 13 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns

### `pipeline.py`

- **[LOW] too-many-params** - `pipeline.py:17`  
  'review_repo' takes 8 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object

### `report.py`

- **[MEDIUM] high-complexity** - `report.py:27`  
  'render_markdown' cyclomatic complexity 25 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] long-function** - `report.py:27`  
  'render_markdown' is 91 lines (max 60)  
  *Why it matters*: a function longer than a screen cannot be diffed or reviewed as a unit, so changes to it are approved without being understood.  
  *Fix*: split it along its comment headings into separate functions

### `review.py`

- **[LOW] too-many-params** - `review.py:196`  
  'record' takes 9 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object
- **[MEDIUM] high-complexity** - `review.py:225`  
  'health' cyclomatic complexity 12 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns

## Duplicated blocks

| similarity | first | second |
|---|---|---|
| 100% | `datagen.py:89` _gateway | `datagen.py:271` _reporting |

## Complexity hot spots

| function | location | cc | nesting | lines | params |
|---|---|---|---|---|---|
| _check_imports | `analyzers.py:669` | 25 | 5 | 37 | 1 |
| render_markdown | `report.py:27` | 25 | 2 | 91 | 4 |
| _terminates | `analyzers.py:240` | 22 | 7 | 33 | 1 |
| _security_call | `analyzers.py:338` | 19 | 3 | 37 | 2 |
| _check_unused_and_shadowed | `analyzers.py:553` | 17 | 2 | 35 | 2 |
| deterministic_policy | `agent.py:174` | 16 | 0 | 65 | 1 |
| policy | `agent.py:182` | 16 | 3 | 55 | 3 |
| _check_off_by_one | `analyzers.py:481` | 16 | 2 | 33 | 2 |
| parse_unified_diff | `diffing.py:84` | 14 | 3 | 35 | 1 |
| find_duplicates | `duplication.py:98` | 13 | 3 | 33 | 4 |

## Agent investigation trace

```
=== Agent trace: code-review-agent (19 steps) ===
[1] list_files {}
    thought: Start by establishing the review scope.
    -> 14 python files:
__init__.py
agent.py
agent_core.py
analyzers.py
churn.py
datagen.py
diffing.py
duplication.py
evaluation.py
llm.py
metrics.py
pipeline.py
report.py
review.py
[2] analyze_file {"path": "__init__.py"}
    thought: 14 file(s) still unreviewed; take '__init__.py' next.
    -> __init__.py: 0 findings; sloc=2 funcs=0 max_cc=0 coupling=0
[3] analyze_file {"path": "agent.py"}
    thought: 13 file(s) still unreviewed; take 'agent.py' next.
    -> agent.py: 6 findings (medium=5, low=1); sloc=232 funcs=11 max_cc=16 coupling=4
[4] analyze_file {"path": "agent_core.py"}
    thought: 12 file(s) still unreviewed; take 'agent_core.py' next.
    -> agent_core.py: 9 findings (low=9); sloc=101 funcs=10 max_cc=7 coupling=5
[5] analyze_file {"path": "analyzers.py"}
    thought: 11 file(s) still unreviewed; take 'analyzers.py' next.
    -> analyzers.py: 8 findings (medium=8); sloc=686 funcs=35 max_cc=25 coupling=5
[6] analyze_file {"path": "churn.py"}
    thought: 10 file(s) still unreviewed; take 'churn.py' next.
    -> churn.py: 0 findings; sloc=92 funcs=7 max_cc=8 coupling=4
[7] analyze_file {"path": "datagen.py"}
    thought: 9 file(s) still unreviewed; take 'datagen.py' next.
    -> datagen.py: 4 findings (medium=2, low=2); sloc=469 funcs=18 max_cc=4 coupling=5
[8] analyze_file {"path": "diffing.py"}
    thought: 8 file(s) still unreviewed; take 'diffing.py' next.
    -> diffing.py: 2 findings (medium=2); sloc=133 funcs=7 max_cc=14 coupling=5
[9] analyze_file {"path": "duplication.py"}
    thought: 7 file(s) still unreviewed; take 'duplication.py' next.
    -> duplication.py: 2 findings (medium=2); sloc=120 funcs=8 max_cc=13 coupling=4
[10] analyze_file {"path": "evaluation.py"}
    thought: 6 file(s) still unreviewed; take 'evaluation.py' next.
    -> evaluation.py: 0 findings; sloc=67 funcs=5 max_cc=9 coupling=2
[11] analyze_file {"path": "llm.py"}
    thought: 5 file(s) still unreviewed; take 'llm.py' next.
    -> llm.py: 0 findings; sloc=46 funcs=3 max_cc=6 coupling=3
[12] analyze_file {"path": "metrics.py"}
    thought: 4 file(s) still unreviewed; take 'metrics.py' next.
    -> metrics.py: 0 findings; sloc=129 funcs=10 max_cc=7 coupling=3
[13] analyze_file {"path": "pipeline.py"}
    thought: 3 file(s) still unreviewed; take 'pipeline.py' next.
    -> pipeline.py: 1 findings (low=1); sloc=54 funcs=4 max_cc=3 coupling=2
[14] analyze_file {"path": "report.py"}
    thought: 2 file(s) still unreviewed; take 'report.py' next.
    -> report.py: 2 findings (medium=2); sloc=120 funcs=3 max_cc=25 coupling=4
[15] analyze_file {"path": "review.py"}
    thought: 1 file(s) still unreviewed; take 'review.py' next.
    -> review.py: 2 findings (medium=1, low=1); sloc=231 funcs=20 max_cc=12 coupling=4
[16] duplicate_scan {}
    thought: Every file is parsed, so clone detection can now compare all of them at once.
    -> 1 duplicate pair(s), 1 finding(s) recorded: datagen.py:89~datagen.py:271 (100%)
[17] complexity_report {"top": 5}
    thought: Inspect the complexity hot spots that drive risk ranking.
    -> worst functions:
analyzers.py:669 _check_imports cc=25 nesting=5 len=37 params=1
report.py:27 render_markdown cc=25 nesting=2 len=91 params=4
analyzers.py:240 _terminates cc=22 nesting=7 len=33 params=1
analyzers.py:338 _security_call cc=19 nesting=3 len=37 params=2
analyzers.py:553 _check_unused_an
[18] search_pattern {"pattern": "(?i)\\w*(?:secret|api[_-]?key|password|passwd|token)\\w*\\s*[:=]\\s*[\\\"']?[A-Za-z0-9+/_\\-]{12,}", "inclu
    thought: AST passes only see Python; search config files for credentials they cannot reach.
    -> 0 matches
[19] finish {"answer": "reviewed 14 files, 37 findings"}
    thought: Scope covered: 37 findings across 14 files.
    -> reviewed 14 files, 37 findings
```

