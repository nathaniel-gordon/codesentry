# Code Review

- **Repository**: `C:\Users\HC\AppData\Local\Programs\Python\Python314\Lib\json`
- **Mode**: full
- **Generated**: 2026-08-25 04:48 UTC
- **Files reviewed**: 6  |  **SLOC**: 1169
- **Churn signal**: static-proxy

## Health score: 53.0/100 (grade F)

| penalty | points |
|---|---|
| finding_density | 18.44 |
| complexity | 20.00 |
| duplication | 0.00 |
| documentation | 8.57 |

Average cyclomatic complexity 9.48, public-API docstring coverage 57%, weighted severity 98.0.

## Findings by severity

| severity | count |
|---|---|
| critical | 0 |
| high | 2 |
| medium | 24 |
| low | 14 |

## Findings by category

| category | count |
|---|---|
| complexity | 31 |
| correctness | 3 |
| maintainability | 6 |

## Top risks (severity x complexity x churn)

| risk | severity | location | rule | message |
|---|---|---|---|---|
| 18.0 | medium | `encoder.py:265` | high-complexity | '_make_iterencode' cyclomatic complexity 60 (max 10) |
| 18.0 | medium | `encoder.py:265` | long-function | '_make_iterencode' is 197 lines (max 60) |
| 18.0 | medium | `encoder.py:265` | shadowed-builtin | parameter 'dict' shadows the builtin of the same name |
| 18.0 | medium | `encoder.py:280` | deep-nesting | '_iterencode_list' nests control flow 10 levels deep (max 4) |
| 18.0 | medium | `encoder.py:280` | high-complexity | '_iterencode_list' cyclomatic complexity 19 (max 10) |
| 18.0 | medium | `encoder.py:339` | deep-nesting | '_iterencode_dict' nests control flow 10 levels deep (max 4) |
| 18.0 | medium | `encoder.py:339` | high-complexity | '_iterencode_dict' cyclomatic complexity 29 (max 10) |
| 18.0 | medium | `encoder.py:339` | long-function | '_iterencode_dict' is 86 lines (max 60) |
| 18.0 | medium | `encoder.py:426` | deep-nesting | '_iterencode' nests control flow 10 levels deep (max 4) |
| 18.0 | medium | `encoder.py:426` | high-complexity | '_iterencode' cyclomatic complexity 14 (max 10) |

## Riskiest files

| file | risk | findings | sloc | max cc |
|---|---|---|---|---|
| `encoder.py` | 204.9 | 14 | 389 | 60 |
| `decoder.py` | 55.7 | 8 | 305 | 23 |
| `__init__.py` | 41.5 | 9 | 292 | 13 |
| `tool.py` | 40.5 | 5 | 104 | 11 |
| `scanner.py` | 30.8 | 4 | 64 | 22 |

## Findings


### `__init__.py`

- **[MEDIUM] long-function** - `__init__.py:120`  
  'dump' is 63 lines (max 60)  
  *Why it matters*: a function longer than a screen cannot be diffed or reviewed as a unit, so changes to it are approved without being understood.  
  *Fix*: split it along its comment headings into separate functions
- **[LOW] too-many-params** - `__init__.py:120`  
  'dump' takes 11 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object
- **[LOW] too-many-params** - `__init__.py:185`  
  'dumps' takes 10 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object
- **[MEDIUM] high-complexity** - `__init__.py:248`  
  'detect_encoding' cyclomatic complexity 13 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[LOW] missing-docstring** - `__init__.py:248`  
  public function 'detect_encoding' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[LOW] too-many-params** - `__init__.py:278`  
  'load' takes 7 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object
- **[MEDIUM] high-complexity** - `__init__.py:304`  
  'loads' cyclomatic complexity 12 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] long-function** - `__init__.py:304`  
  'loads' is 62 lines (max 60)  
  *Why it matters*: a function longer than a screen cannot be diffed or reviewed as a unit, so changes to it are approved without being understood.  
  *Fix*: split it along its comment headings into separate functions
- **[LOW] too-many-params** - `__init__.py:304`  
  'loads' takes 7 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object

### `decoder.py`

- **[MEDIUM] high-complexity** - `decoder.py:70`  
  'py_scanstring' cyclomatic complexity 13 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] high-complexity** - `decoder.py:137`  
  'JSONObject' cyclomatic complexity 23 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] long-function** - `decoder.py:137`  
  'JSONObject' is 83 lines (max 60)  
  *Why it matters*: a function longer than a screen cannot be diffed or reviewed as a unit, so changes to it are approved without being understood.  
  *Fix*: split it along its comment headings into separate functions
- **[LOW] missing-docstring** - `decoder.py:137`  
  public function 'JSONObject' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[LOW] too-many-params** - `decoder.py:137`  
  'JSONObject' takes 8 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object
- **[MEDIUM] high-complexity** - `decoder.py:221`  
  'JSONArray' cyclomatic complexity 12 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[LOW] missing-docstring** - `decoder.py:221`  
  public function 'JSONArray' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[LOW] too-many-params** - `decoder.py:292`  
  '__init__' takes 7 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object

### `encoder.py`

- **[LOW] too-many-params** - `encoder.py:105`  
  '__init__' takes 9 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object
- **[MEDIUM] high-complexity** - `encoder.py:207`  
  'iterencode' cyclomatic complexity 11 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] high-complexity** - `encoder.py:265`  
  '_make_iterencode' cyclomatic complexity 60 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] long-function** - `encoder.py:265`  
  '_make_iterencode' is 197 lines (max 60)  
  *Why it matters*: a function longer than a screen cannot be diffed or reviewed as a unit, so changes to it are approved without being understood.  
  *Fix*: split it along its comment headings into separate functions
- **[MEDIUM] shadowed-builtin** - `encoder.py:265`  
  parameter 'dict' shadows the builtin of the same name  
  *Why it matters*: rebinding a builtin makes later code in the same scope call the local value instead, producing TypeErrors far from the assignment.  
  *Fix*: rename it (e.g. 'dict_' or a domain word)
- **[LOW] too-many-params** - `encoder.py:265`  
  '_make_iterencode' takes 20 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object
- **[LOW] todo-marker** - `encoder.py:267`  
  ## HACK: hand-optimized bytecode; turn globals into locals  
  *Why it matters*: a TODO in code is an issue nobody is tracking and nobody is assigned.  
  *Fix*: file an issue and link it, or delete the note
- **[MEDIUM] deep-nesting** - `encoder.py:280` in `_make_iterencode()`  
  '_iterencode_list' nests control flow 10 levels deep (max 4)  
  *Why it matters*: each nesting level multiplies the conditions a reader must track; deeply nested code is where inverted-condition bugs live.  
  *Fix*: invert conditions to return early, or extract the inner loop
- **[MEDIUM] high-complexity** - `encoder.py:280` in `_make_iterencode()`  
  '_iterencode_list' cyclomatic complexity 19 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] deep-nesting** - `encoder.py:339` in `_make_iterencode()`  
  '_iterencode_dict' nests control flow 10 levels deep (max 4)  
  *Why it matters*: each nesting level multiplies the conditions a reader must track; deeply nested code is where inverted-condition bugs live.  
  *Fix*: invert conditions to return early, or extract the inner loop
- **[MEDIUM] high-complexity** - `encoder.py:339` in `_make_iterencode()`  
  '_iterencode_dict' cyclomatic complexity 29 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] long-function** - `encoder.py:339` in `_make_iterencode()`  
  '_iterencode_dict' is 86 lines (max 60)  
  *Why it matters*: a function longer than a screen cannot be diffed or reviewed as a unit, so changes to it are approved without being understood.  
  *Fix*: split it along its comment headings into separate functions
- **[MEDIUM] deep-nesting** - `encoder.py:426` in `_make_iterencode()`  
  '_iterencode' nests control flow 10 levels deep (max 4)  
  *Why it matters*: each nesting level multiplies the conditions a reader must track; deeply nested code is where inverted-condition bugs live.  
  *Fix*: invert conditions to return early, or extract the inner loop
- **[MEDIUM] high-complexity** - `encoder.py:426` in `_make_iterencode()`  
  '_iterencode' cyclomatic complexity 14 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns

### `scanner.py`

- **[MEDIUM] high-complexity** - `scanner.py:15`  
  'py_make_scanner' cyclomatic complexity 22 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[LOW] missing-docstring** - `scanner.py:15`  
  public function 'py_make_scanner' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[MEDIUM] deep-nesting** - `scanner.py:28` in `py_make_scanner()`  
  '_scan_once' nests control flow 6 levels deep (max 4)  
  *Why it matters*: each nesting level multiplies the conditions a reader must track; deeply nested code is where inverted-condition bugs live.  
  *Fix*: invert conditions to return early, or extract the inner loop
- **[MEDIUM] high-complexity** - `scanner.py:28` in `py_make_scanner()`  
  '_scan_once' cyclomatic complexity 22 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns

### `tool.py`

- **[MEDIUM] high-complexity** - `tool.py:44`  
  'main' cyclomatic complexity 11 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] long-function** - `tool.py:44`  
  'main' is 72 lines (max 60)  
  *Why it matters*: a function longer than a screen cannot be diffed or reviewed as a unit, so changes to it are approved without being understood.  
  *Fix*: split it along its comment headings into separate functions
- **[LOW] missing-docstring** - `tool.py:44`  
  public function 'main' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[HIGH] unclosed-resource** - `tool.py:88` in `main()`  
  open() result is not managed by a `with` block  
  *Why it matters*: a file handle left outside `with` is only closed by the garbage collector; on an exception the write is never flushed.  
  *Fix*: wrap it: `with open(path) as fh:` so it closes on any exit
- **[HIGH] unclosed-resource** - `tool.py:102` in `main()`  
  open() result is not managed by a `with` block  
  *Why it matters*: a file handle left outside `with` is only closed by the garbage collector; on an exception the write is never flushed.  
  *Fix*: wrap it: `with open(path) as fh:` so it closes on any exit
## Complexity hot spots

| function | location | cc | nesting | lines | params |
|---|---|---|---|---|---|
| _make_iterencode | `encoder.py:265` | 60 | 0 | 197 | 20 |
| _iterencode_dict | `encoder.py:339` | 29 | 10 | 86 | 2 |
| JSONObject | `decoder.py:137` | 23 | 4 | 83 | 8 |
| py_make_scanner | `scanner.py:15` | 22 | 0 | 57 | 1 |
| _scan_once | `scanner.py:28` | 22 | 6 | 36 | 2 |
| _iterencode_list | `encoder.py:280` | 19 | 10 | 58 | 2 |
| _iterencode | `encoder.py:426` | 14 | 10 | 35 | 2 |
| detect_encoding | `__init__.py:248` | 13 | 3 | 28 | 1 |
| py_scanstring | `decoder.py:70` | 13 | 4 | 58 | 5 |
| loads | `__init__.py:304` | 12 | 2 | 62 | 7 |

## Agent investigation trace

```
=== Agent trace: code-review-agent (11 steps) ===
[1] list_files {}
    thought: Start by establishing the review scope.
    -> 6 python files:
__init__.py
__main__.py
decoder.py
encoder.py
scanner.py
tool.py
[2] analyze_file {"path": "__init__.py"}
    thought: 6 file(s) still unreviewed; take '__init__.py' next.
    -> __init__.py: 9 findings (medium=4, low=5); sloc=292 funcs=5 max_cc=13 coupling=1
[3] analyze_file {"path": "__main__.py"}
    thought: 5 file(s) still unreviewed; take '__main__.py' next.
    -> __main__.py: 0 findings; sloc=15 funcs=0 max_cc=0 coupling=1
[4] analyze_file {"path": "decoder.py"}
    thought: 4 file(s) still unreviewed; take 'decoder.py' next.
    -> decoder.py: 8 findings (medium=4, low=4); sloc=305 funcs=9 max_cc=23 coupling=3
[5] analyze_file {"path": "encoder.py"}
    thought: 3 file(s) still unreviewed; take 'encoder.py' next.
    -> encoder.py: 14 findings (medium=11, low=3); sloc=389 funcs=13 max_cc=60 coupling=2
[6] analyze_file {"path": "scanner.py"}
    thought: 2 file(s) still unreviewed; take 'scanner.py' next.
    -> scanner.py: 4 findings (medium=3, low=1); sloc=64 funcs=3 max_cc=22 coupling=2
[7] analyze_file {"path": "tool.py"}
    thought: 1 file(s) still unreviewed; take 'tool.py' next.
    -> tool.py: 5 findings (high=2, medium=2, low=1); sloc=104 funcs=3 max_cc=11 coupling=5
[8] duplicate_scan {}
    thought: Every file is parsed, so clone detection can now compare all of them at once.
    -> no duplicate blocks above the similarity threshold
[9] complexity_report {"top": 5}
    thought: Inspect the complexity hot spots that drive risk ranking.
    -> worst functions:
encoder.py:265 _make_iterencode cc=60 nesting=0 len=197 params=20
encoder.py:339 _iterencode_dict cc=29 nesting=10 len=86 params=2
decoder.py:137 JSONObject cc=23 nesting=4 len=83 params=8
scanner.py:15 py_make_scanner cc=22 nesting=0 len=57 params=1
scanner.py:28 _scan_once cc=22 n
[10] search_pattern {"pattern": "(?i)\\w*(?:secret|api[_-]?key|password|passwd|token)\\w*\\s*[:=]\\s*[\\\"']?[A-Za-z0-9+/_\\-]{12,}", "inclu
    thought: AST passes only see Python; search config files for credentials they cannot reach.
    -> 0 matches
[11] finish {"answer": "reviewed 6 files, 40 findings"}
    thought: Scope covered: 40 findings across 6 files.
    -> reviewed 6 files, 40 findings
```

