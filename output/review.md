# Demo repo review

- **Repository**: `d:\khalid\code-review-agent\output\demo_repo\base`
- **Mode**: full
- **Generated**: 2026-08-25 22:59 UTC
- **Files reviewed**: 12  |  **SLOC**: 250
- **Churn signal**: static-proxy

## Health score: 32.7/100 (grade F)

| penalty | points |
|---|---|
| finding_density | 55.00 |
| complexity | 0.00 |
| duplication | 11.54 |
| documentation | 0.80 |

Average cyclomatic complexity 2.62, public-API docstring coverage 96%, weighted severity 124.0.

## Findings by severity

| severity | count |
|---|---|
| critical | 7 |
| high | 5 |
| medium | 6 |
| low | 6 |

## Findings by category

| category | count |
|---|---|
| complexity | 5 |
| correctness | 3 |
| maintainability | 7 |
| security | 9 |

## Top risks (severity x complexity x churn)

| risk | severity | location | rule | message |
|---|---|---|---|---|
| 16.4 | critical | `payments/gateway.py:6` | hardcoded-secret | 'API_TOKEN' is assigned a literal credential-looking string |
| 16.4 | critical | `payments/gateway.py:14` | sql-injection | 'sql' builds a SQL string by interpolation |
| 16.4 | critical | `payments/gateway.py:21` | sql-injection | SQL statement is assembled from a runtime value |
| 16.4 | critical | `payments/gateway.py:27` | eval-exec | use of eval() on a runtime value is a code-injection sink |
| 16.4 | critical | `payments/gateway.py:32` | shell-true | subprocess called with shell=True |
| 16.4 | critical | `payments/gateway.py:37` | os-system | os.system() executes through the shell |
| 14.4 | medium | `inventory/reporting.py:1` | high-coupling | module imports 13 distinct top-level modules (max 12) |
| 14.4 | medium | `inventory/reporting.py:15` | deep-nesting | 'build_report' nests control flow 6 levels deep (max 4) |
| 14.4 | medium | `inventory/reporting.py:15` | high-complexity | 'build_report' cyclomatic complexity 21 (max 10) |
| 14.4 | medium | `inventory/reporting.py:15` | long-function | 'build_report' is 65 lines (max 60) |

## Riskiest files

| file | risk | findings | sloc | max cc |
|---|---|---|---|---|
| `payments/gateway.py` | 108.1 | 7 | 29 | 1 |
| `inventory/reporting.py` | 62.4 | 5 | 79 | 21 |
| `payments/validation.py` | 39.3 | 4 | 21 | 4 |
| `utils/legacy.py` | 19.3 | 7 | 22 | 5 |
| `payments/settings.ini` | 10.7 | 1 | - | - |

## Findings


### `inventory/reporting.py`

- **[MEDIUM] high-coupling** - `inventory/reporting.py:1`  
  module imports 13 distinct top-level modules (max 12)  
  *Why it matters*: a module importing many others must be rebuilt, retested and redeployed whenever any of them changes.  
  *Fix*: split the module by responsibility so each part has few dependencies
- **[MEDIUM] deep-nesting** - `inventory/reporting.py:15`  
  'build_report' nests control flow 6 levels deep (max 4)  
  *Why it matters*: each nesting level multiplies the conditions a reader must track; deeply nested code is where inverted-condition bugs live.  
  *Fix*: invert conditions to return early, or extract the inner loop
- **[MEDIUM] high-complexity** - `inventory/reporting.py:15`  
  'build_report' cyclomatic complexity 21 (max 10)  
  *Why it matters*: cyclomatic complexity is the number of independent paths; past ~10 the function cannot be covered by tests or held in a reviewer's head.  
  *Fix*: extract the branch bodies into named helpers and use early returns
- **[MEDIUM] long-function** - `inventory/reporting.py:15`  
  'build_report' is 65 lines (max 60)  
  *Why it matters*: a function longer than a screen cannot be diffed or reviewed as a unit, so changes to it are approved without being understood.  
  *Fix*: split it along its comment headings into separate functions
- **[LOW] too-many-params** - `inventory/reporting.py:15`  
  'build_report' takes 8 parameters (max 6)  
  *Why it matters*: long parameter lists are positional-argument bugs waiting to happen and signal that the function owns several responsibilities.  
  *Fix*: group the related ones into a dataclass or config object

### `payments/gateway.py`

- **[CRITICAL] hardcoded-secret** - `payments/gateway.py:6`  
  'API_TOKEN' is assigned a literal credential-looking string  
  *Why it matters*: a literal credential is copied into every clone, backup and CI log; rotating it means shipping code, so in practice it never gets rotated.  
  *Fix*: read it from os.environ / a secret manager and rotate this value
- **[CRITICAL] sql-injection** - `payments/gateway.py:14` in `charge_customer()`  
  'sql' builds a SQL string by interpolation  
  *Why it matters*: concatenating values into SQL lets input change the query's meaning (dropping tables or reading other tenants' rows) instead of its data.  
  *Fix*: keep the statement constant and pass values as parameters
- **[CRITICAL] sql-injection** - `payments/gateway.py:21` in `refund()`  
  SQL statement is assembled from a runtime value  
  *Why it matters*: concatenating values into SQL lets input change the query's meaning (dropping tables or reading other tenants' rows) instead of its data.  
  *Fix*: use a parameterised query: execute(sql, (value,))
- **[CRITICAL] eval-exec** - `payments/gateway.py:27` in `apply_discount_rule()`  
  use of eval() on a runtime value is a code-injection sink  
  *Why it matters*: eval/exec compile attacker-controlled text into live code; one unescaped input turns a data bug into remote code execution.  
  *Fix*: replace with ast.literal_eval() or an explicit dispatch dict
- **[CRITICAL] shell-true** - `payments/gateway.py:32` in `sync_ledger()`  
  subprocess called with shell=True  
  *Why it matters*: shell=True hands the string to /bin/sh, so any ';' or '$(...)' in an interpolated value runs as a second command with your privileges.  
  *Fix*: pass an argument list (['git', 'clone', url]) and drop shell=True
- **[CRITICAL] os-system** - `payments/gateway.py:37` in `rotate_logs()`  
  os.system() executes through the shell  
  *Why it matters*: os.system() always goes through the shell and gives you no way to pass arguments safely, so every call site is a potential injection point.  
  *Fix*: use subprocess.run([...], shell=False) and check returncode
- **[HIGH] unsafe-deserialization** - `payments/gateway.py:42` in `load_session()`  
  pickle.loads() rebuilds arbitrary objects from untrusted bytes  
  *Why it matters*: pickle/marshal/yaml.load reconstruct arbitrary objects, which executes code chosen by whoever produced the byte stream.  
  *Fix*: use json, or verify an HMAC over the payload before loading

### `payments/settings.ini`

- **[CRITICAL] hardcoded-secret** - `payments/settings.ini:3`  
  configuration key 'stripe_secret_key' holds a literal credential  
  *Why it matters*: a literal credential is copied into every clone, backup and CI log; rotating it means shipping code, so in practice it never gets rotated.  
  *Fix*: move the value to a secret manager, reference it by name, and rotate it

### `payments/validation.py`

- **[HIGH] assert-validation** - `payments/validation.py:8` in `validate_amount()`  
  assert validates argument(s) of 'validate_amount'  
  *Why it matters*: asserts are stripped under `python -O`, so validation written as an assert silently disappears in optimised production builds.  
  *Fix*: raise ValueError(...) so the check survives `python -O`
- **[HIGH] mutable-default** - `payments/validation.py:12`  
  function 'collect_errors' has a mutable default argument  
  *Why it matters*: the default object is created once at def time and shared by every call, so state leaks between unrelated callers.  
  *Fix*: default to None and build the container inside the function
- **[HIGH] is-literal** - `payments/validation.py:14` in `collect_errors()`  
  `is` used to compare against the literal 'USD'  
  *Why it matters*: `is` compares identity, and equal literals are only sometimes the same object (interning), so the comparison works in tests and fails in prod.  
  *Fix*: use == / != for value comparison; keep `is` for None
- **[HIGH] inconsistent-return** - `payments/validation.py:21`  
  'normalize_status' returns a value on some paths and falls through to an implicit None on others  
  *Why it matters*: some paths return a value and others fall off the end returning None, so callers crash on attribute access for a subset of inputs.  
  *Fix*: add a final `return` with an explicit value, or raise

### `utils/legacy.py`

- **[LOW] missing-docstring** - `utils/legacy.py:1`  
  module has no docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: add a one-line module docstring describing its responsibility
- **[LOW] unused-import** - `utils/legacy.py:1`  
  import 'hashlib' is never used  
  *Why it matters*: dead imports slow start-up, create phantom dependencies and hide which modules are really coupled.  
  *Fix*: remove the import
- **[LOW] todo-marker** - `utils/legacy.py:4`  
  # TODO: delete this module once the v2 exporter ships  
  *Why it matters*: a TODO in code is an issue nobody is tracking and nobody is assigned.  
  *Fix*: file an issue and link it, or delete the note
- **[MEDIUM] duplicate-block** - `utils/legacy.py:5` in `flatten_rows()`  
  'flatten_rows' is 89% structurally identical to 'expand_records' at utils/helpers.py:4  
  *Why it matters*: copy-pasted logic means every bug must be fixed N times; in practice only the copy that was reported gets fixed.  
  *Fix*: extract the shared logic into one function and call it from both sites
- **[LOW] missing-docstring** - `utils/legacy.py:5`  
  public function 'flatten_rows' lacks a docstring  
  *Why it matters*: public API without a docstring forces every caller to read the implementation, and makes intent-vs-behaviour bugs unprovable.  
  *Fix*: document what it returns and which errors it raises
- **[MEDIUM] dead-code** - `utils/legacy.py:19` in `flatten_rows()`  
  statement is unreachable: the preceding return always exits this block  
  *Why it matters*: unreachable code is never executed or tested, so it rots and then misleads the next reader into believing it runs.  
  *Fix*: delete it, or move it above the exit statement
- **[LOW] unused-private** - `utils/legacy.py:27`  
  private helper '_stale_checksum' is never called in this module  
  *Why it matters*: a private helper nobody calls is dead weight that still has to be read, understood and kept compiling.  
  *Fix*: delete it, or make it public if other modules need it

## Duplicated blocks

| similarity | first | second |
|---|---|---|
| 89% | `utils/helpers.py:4` expand_records | `utils/legacy.py:5` flatten_rows |

## Complexity hot spots

| function | location | cc | nesting | lines | params |
|---|---|---|---|---|---|
| build_report | `inventory/reporting.py:15` | 21 | 6 | 65 | 8 |
| expand_records | `utils/helpers.py:4` | 5 | 4 | 15 | 1 |
| flatten_rows | `utils/legacy.py:5` | 5 | 4 | 15 | 1 |
| normalize_status | `payments/validation.py:21` | 4 | 1 | 8 | 1 |
| find | `core/models.py:29` | 3 | 2 | 6 | 2 |
| find_gaps | `inventory/stock.py:9` | 3 | 2 | 7 | 1 |
| collect_errors | `payments/validation.py:12` | 3 | 1 | 7 | 2 |
| total_available | `core/models.py:25` | 2 | 0 | 3 | 1 |
| reorder_point | `inventory/stock.py:23` | 2 | 1 | 6 | 2 |
| persist | `inventory/stock.py:31` | 2 | 2 | 7 | 2 |

## Agent investigation trace

```
=== Agent trace: code-review-agent (18 steps) ===
[1] list_files {}
    thought: Start by establishing the review scope.
    -> 12 python files:
core/__init__.py
core/config.py
core/models.py
inventory/__init__.py
inventory/reporting.py
inventory/stock.py
payments/__init__.py
payments/gateway.py
payments/validation.py
utils/__init__.py
utils/helpers.py
utils/legacy.py
[2] analyze_file {"path": "core/__init__.py"}
    thought: 12 file(s) still unreviewed; take 'core/__init__.py' next.
    -> core/__init__.py: 0 findings; sloc=1 funcs=0 max_cc=0 coupling=0
[3] analyze_file {"path": "core/config.py"}
    thought: 11 file(s) still unreviewed; take 'core/config.py' next.
    -> core/config.py: 0 findings; sloc=18 funcs=2 max_cc=1 coupling=1
[4] analyze_file {"path": "core/models.py"}
    thought: 10 file(s) still unreviewed; take 'core/models.py' next.
    -> core/models.py: 0 findings; sloc=25 funcs=3 max_cc=3 coupling=1
[5] analyze_file {"path": "inventory/__init__.py"}
    thought: 9 file(s) still unreviewed; take 'inventory/__init__.py' next.
    -> inventory/__init__.py: 0 findings; sloc=1 funcs=0 max_cc=0 coupling=0
[6] analyze_file {"path": "inventory/reporting.py"}
    thought: 8 file(s) still unreviewed; take 'inventory/reporting.py' next.
    -> inventory/reporting.py: 5 findings (medium=4, low=1); sloc=79 funcs=1 max_cc=21 coupling=13
[7] analyze_file {"path": "inventory/stock.py"}
    thought: 7 file(s) still unreviewed; take 'inventory/stock.py' next.
    -> ERROR: AttributeError: '_ModuleAnalysis' object has no attribute '_resource_is_managed'
[8] analyze_file {"path": "payments/__init__.py"}
    thought: 6 file(s) still unreviewed; take 'payments/__init__.py' next.
    -> payments/__init__.py: 0 findings; sloc=1 funcs=0 max_cc=0 coupling=0
[9] analyze_file {"path": "payments/gateway.py"}
    thought: 5 file(s) still unreviewed; take 'payments/gateway.py' next.
    -> payments/gateway.py: 7 findings (critical=6, high=1); sloc=29 funcs=7 max_cc=1 coupling=3
[10] analyze_file {"path": "payments/validation.py"}
    thought: 4 file(s) still unreviewed; take 'payments/validation.py' next.
    -> payments/validation.py: 4 findings (high=4); sloc=21 funcs=3 max_cc=4 coupling=0
[11] analyze_file {"path": "utils/__init__.py"}
    thought: 3 file(s) still unreviewed; take 'utils/__init__.py' next.
    -> utils/__init__.py: 0 findings; sloc=1 funcs=0 max_cc=0 coupling=0
[12] analyze_file {"path": "utils/helpers.py"}
    thought: 2 file(s) still unreviewed; take 'utils/helpers.py' next.
    -> utils/helpers.py: 0 findings; sloc=16 funcs=1 max_cc=5 coupling=0
[13] analyze_file {"path": "utils/legacy.py"}
    thought: 1 file(s) still unreviewed; take 'utils/legacy.py' next.
    -> utils/legacy.py: 6 findings (medium=1, low=5); sloc=22 funcs=3 max_cc=5 coupling=2
[14] duplicate_scan {}
    thought: Every file is parsed, so clone detection can now compare all of them at once.
    -> 1 duplicate pair(s), 1 finding(s) recorded: utils/helpers.py:4~utils/legacy.py:5 (89%)
[15] complexity_report {"top": 5}
    thought: Inspect the complexity hot spots that drive risk ranking.
    -> worst functions:
inventory/reporting.py:15 build_report cc=21 nesting=6 len=65 params=8
utils/helpers.py:4 expand_records cc=5 nesting=4 len=15 params=1
utils/legacy.py:5 flatten_rows cc=5 nesting=4 len=15 params=1
payments/validation.py:21 normalize_status cc=4 nesting=1 len=8 params=1
core/models.
[16] search_pattern {"pattern": "(?i)\\w*(?:secret|api[_-]?key|password|passwd|token)\\w*\\s*[:=]\\s*[\\\"']?[A-Za-z0-9+/_\\-]{12,}", "inclu
    thought: AST passes only see Python; search config files for credentials they cannot reach.
    -> 1 matches:
payments/settings.ini:3:stripe_secret_key = sk_live_4b81c0d9e7f2a635
[17] record_finding {"file": "payments/settings.ini", "line": 3, "rule": "hardcoded-secret", "message": "configuration key 'stripe_secret_ke
    thought: 'payments/settings.ini:3' assigns a credential in a config file that ships with the repo.
    -> recorded hardcoded-secret at payments/settings.ini:3
[18] finish {"answer": "reviewed 12 files, 24 findings"}
    thought: Scope covered: 24 findings across 12 files.
    -> reviewed 12 files, 24 findings
```

