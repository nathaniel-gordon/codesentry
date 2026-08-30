"""AST-based Python analyzers. Each returns Finding objects with line-accurate locations.

Four passes run over one parsed module: security, correctness, complexity and
maintainability. Every rule is implemented against the `ast` node graph (not text
matching) so it survives formatting changes and cannot be fooled by comments; the
only textual rules are the ones that are genuinely textual (line length, TODO
markers), which have no AST representation at all.

Rule metadata (severity, category, WHY it matters) lives in one table, `RULES`, so
a reviewer can audit the whole policy in one place and reports stay consistent.
"""
from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field
from typing import Iterator

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_WEIGHT = {"critical": 10.0, "high": 6.0, "medium": 3.0, "low": 1.0}
CATEGORIES = ("security", "correctness", "complexity", "maintainability")


@dataclass
class Finding:
    """One reviewable defect at a concrete `file:line`."""

    file: str
    line: int
    rule: str
    severity: str          # critical | high | medium | low
    message: str
    suggestion: str
    category: str = "correctness"
    why: str = ""
    function: str = ""
    risk: float = 0.0

    def __post_init__(self) -> None:
        # One vocabulary everywhere: severity and category are closed sets, and
        # the risk model indexes SEVERITY_WEIGHT by severity, so an out-of-
        # vocabulary value must be rejected here rather than crashing scoring.
        self.severity = self.severity.strip().lower()
        self.category = self.category.strip().lower()
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(
                f"unknown severity {self.severity!r}; expected one of "
                f"{', '.join(SEVERITY_ORDER)}")
        if self.category not in CATEGORIES:
            raise ValueError(
                f"unknown category {self.category!r}; expected one of "
                f"{', '.join(CATEGORIES)}")
        self.line = max(1, int(self.line))

    @property
    def key(self) -> tuple[str, int, str]:
        """Stable identity used for dedupe, diff filtering and test assertions."""
        return (self.file, self.line, self.rule)

    def location(self) -> str:
        """Return the canonical `path:line` label."""
        return f"{self.file}:{self.line}"

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view (machine-readable report rows)."""
        return {
            "file": self.file, "line": self.line, "rule": self.rule,
            "severity": self.severity, "category": self.category,
            "message": self.message, "why": self.why,
            "suggestion": self.suggestion, "function": self.function,
            "risk": round(self.risk, 3),
        }


@dataclass(frozen=True)
class RuleSpec:
    """Static policy for a rule: how bad it is, which pass owns it, and why it matters."""

    severity: str
    category: str
    why: str


RULES: dict[str, RuleSpec] = {
    # --- security ---------------------------------------------------------
    "eval-exec": RuleSpec("critical", "security",
        "eval/exec compile attacker-controlled text into live code; one unescaped "
        "input turns a data bug into remote code execution."),
    "shell-true": RuleSpec("critical", "security",
        "shell=True hands the string to /bin/sh, so any ';' or '$(...)' in an "
        "interpolated value runs as a second command with your privileges."),
    "os-system": RuleSpec("critical", "security",
        "os.system() always goes through the shell and gives you no way to pass "
        "arguments safely, so every call site is a potential injection point."),
    "hardcoded-secret": RuleSpec("critical", "security",
        "a literal credential is copied into every clone, backup and CI log; "
        "rotating it means shipping code, so in practice it never gets rotated."),
    "sql-injection": RuleSpec("critical", "security",
        "concatenating values into SQL lets input change the query's meaning "
        "(dropping tables or reading other tenants' rows) instead of its data."),
    "unsafe-deserialization": RuleSpec("high", "security",
        "pickle/marshal/yaml.load reconstruct arbitrary objects, which executes "
        "code chosen by whoever produced the byte stream."),
    "assert-validation": RuleSpec("high", "security",
        "asserts are stripped under `python -O`, so validation written as an "
        "assert silently disappears in optimised production builds."),
    "weak-hash": RuleSpec("medium", "security",
        "MD5/SHA1 are collision-broken; using them for tokens, signatures or "
        "password derivation lets an attacker forge a matching value."),
    # --- correctness ------------------------------------------------------
    "mutable-default": RuleSpec("high", "correctness",
        "the default object is created once at def time and shared by every "
        "call, so state leaks between unrelated callers."),
    "bare-except": RuleSpec("medium", "correctness",
        "a bare except also swallows KeyboardInterrupt and SystemExit, so the "
        "process becomes unkillable and real errors vanish."),
    "broad-except": RuleSpec("medium", "correctness",
        "catching Exception and discarding it hides the failure; the caller "
        "gets a wrong result instead of a stack trace."),
    "is-literal": RuleSpec("high", "correctness",
        "`is` compares identity, and equal literals are only sometimes the same "
        "object (interning), so the comparison works in tests and fails in prod."),
    "unused-variable": RuleSpec("low", "correctness",
        "a computed-but-unused local is usually a typo or a dropped assignment "
        "- the value the author meant to use is silently discarded."),
    "shadowed-builtin": RuleSpec("medium", "correctness",
        "rebinding a builtin makes later code in the same scope call the local "
        "value instead, producing TypeErrors far from the assignment."),
    "inconsistent-return": RuleSpec("high", "correctness",
        "some paths return a value and others fall off the end returning None, "
        "so callers crash on attribute access for a subset of inputs."),
    "unclosed-resource": RuleSpec("high", "correctness",
        "a file handle left outside `with` is only closed by the garbage "
        "collector; on an exception the write is never flushed."),
    "off-by-one": RuleSpec("high", "correctness",
        "indexing one past the loop bound raises IndexError on the last "
        "iteration - the classic boundary bug that unit tests with short "
        "fixtures often miss."),
    # --- complexity -------------------------------------------------------
    "high-complexity": RuleSpec("medium", "complexity",
        "cyclomatic complexity is the number of independent paths; past ~10 the "
        "function cannot be covered by tests or held in a reviewer's head."),
    "deep-nesting": RuleSpec("medium", "complexity",
        "each nesting level multiplies the conditions a reader must track; "
        "deeply nested code is where inverted-condition bugs live."),
    "long-function": RuleSpec("medium", "complexity",
        "a function longer than a screen cannot be diffed or reviewed as a "
        "unit, so changes to it are approved without being understood."),
    "too-many-params": RuleSpec("low", "complexity",
        "long parameter lists are positional-argument bugs waiting to happen "
        "and signal that the function owns several responsibilities."),
    "high-coupling": RuleSpec("medium", "complexity",
        "a module importing many others must be rebuilt, retested and "
        "redeployed whenever any of them changes."),
    # --- maintainability --------------------------------------------------
    "missing-docstring": RuleSpec("low", "maintainability",
        "public API without a docstring forces every caller to read the "
        "implementation, and makes intent-vs-behaviour bugs unprovable."),
    "dead-code": RuleSpec("medium", "maintainability",
        "unreachable code is never executed or tested, so it rots and then "
        "misleads the next reader into believing it runs."),
    "duplicate-block": RuleSpec("medium", "maintainability",
        "copy-pasted logic means every bug must be fixed N times; in practice "
        "only the copy that was reported gets fixed."),
    "unused-import": RuleSpec("low", "maintainability",
        "dead imports slow start-up, create phantom dependencies and hide "
        "which modules are really coupled."),
    "unused-private": RuleSpec("low", "maintainability",
        "a private helper nobody calls is dead weight that still has to be "
        "read, understood and kept compiling."),
    "long-line": RuleSpec("low", "maintainability",
        "over-long lines defeat side-by-side diffs, which is where review "
        "actually happens."),
    "todo-marker": RuleSpec("low", "maintainability",
        "a TODO in code is an issue nobody is tracking and nobody is assigned."),
    "syntax-error": RuleSpec("critical", "correctness",
        "the module cannot be imported at all, so anything depending on it is "
        "already broken."),
}


@dataclass
class AnalyzerConfig:
    """Thresholds for the tunable rules (all defaults are industry-common)."""

    max_complexity: int = 10
    max_nesting: int = 4
    max_fn_lines: int = 60
    max_params: int = 6
    max_line_len: int = 110
    max_imports: int = 12
    skip_rules: frozenset[str] = field(default_factory=frozenset)


#: Rule packs. The four categories are the packs; there is no fifth grouping,
#: because every rule belongs to exactly one category and inventing an extra
#: bundle would only be a second name for the same set.
PACKS: dict[str, frozenset[str]] = {
    category: frozenset(rule for rule, spec in RULES.items()
                        if spec.category == category)
    for category in CATEGORIES
}

SECRET_RE = re.compile(r"(?i)(password|passwd|secret|api[_-]?key|token|private[_-]?key)")
SECRET_VALUE_RE = re.compile(r"^[A-Za-z0-9+/=_\-.]+$")
#: Targets whose *name* says the value is a name, not the credential itself.
#: `API_KEY_HEADER = "X-Api-Key"` is a constant every HTTP client needs.
SECRET_NAME_SUFFIXES = (
    "_header", "_headers", "_field", "_fields", "_name", "_names", "_env",
    "_envvar", "_env_var", "_var", "_param", "_params", "_key_name", "_column",
    "_prefix", "_suffix", "_label", "_attr", "_arg", "_pattern", "_regex",
    "_re", "_template", "_format", "_message", "_url", "_path", "_scheme",
    "_type", "_kind", "_id",
)
#: Values that are obviously not live credentials. Matched against the value
#: with digits and punctuation stripped, so `changeme_1234` is caught while
#: `rk_test_51Hb9xKLm4NpQ7` (a real key shape) is not.
SECRET_PLACEHOLDER_WORDS = frozenset({
    "changeme", "placeholder", "example", "todo", "redacted", "dummy",
    "sample", "notasecret", "none", "null", "unset", "fake", "secret",
    "password", "token", "apikey", "yourapikey", "insertkeyhere",
})
SECRET_PLACEHOLDER_PREFIXES = ("your", "<", "${", "{{", "xxxx", "****")
SECRET_MIN_LEN = 12
SECRET_MIN_ENTROPY = 3.0

#: A SQL statement head, and the clause each head must be followed by before the
#: string is treated as SQL rather than English prose that happens to contain
#: the word "update" or "select".
SQL_HEAD_RE = re.compile(r"(?s)^\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE|MERGE|"
                         r"CREATE|ALTER|DROP|TRUNCATE)\b(.*)$", re.IGNORECASE)
SQL_REQUIRED_CLAUSE = {
    "select": r"\bfrom\b", "delete": r"\bfrom\b", "insert": r"\binto\b",
    "replace": r"\binto\b", "merge": r"\binto\b", "update": r"\bset\b",
    "create": r"\b(table|index|view|database|schema|trigger)\b",
    "alter": r"\b(table|index|view|database|schema)\b",
    "drop": r"\b(table|index|view|database|schema)\b",
    "truncate": r"\btable\b",
}
SQL_CLAUSE_RE = re.compile(
    r"(?i)\b(from|into|set|where|values|join|table|order\s+by|group\s+by|"
    r"limit|returning|on\s+conflict)\b")
TODO_RE = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b")
SHADOWABLE_BUILTINS = frozenset({
    "all", "any", "bytes", "dict", "dir", "filter", "format", "hash", "id",
    "input", "int", "len", "list", "map", "max", "min", "next", "object",
    "open", "print", "range", "set", "str", "sum", "type", "vars",
})
DESERIALIZERS = {("pickle", "load"), ("pickle", "loads"), ("marshal", "loads"),
                 ("cPickle", "loads"), ("dill", "loads")}


def shannon_entropy(text: str) -> float:
    """Bits of entropy per character. Low for words, high for random tokens."""
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(text)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def _charset_classes(text: str) -> int:
    """How many of {lowercase, uppercase, digit} the value uses.

    Separators are deliberately excluded: counting '_' as a class would let
    `MYAPP_ACCESS_TOKEN` through, which is exactly the name-shaped constant this
    gate exists to reject.
    """
    return sum((
        any(c.islower() for c in text),
        any(c.isupper() for c in text),
        any(c.isdigit() for c in text),
    ))


def looks_like_secret_name(label: str) -> bool:
    """True when the assignment target names a credential rather than a name of one.

    `API_KEY` is a credential. `API_KEY_HEADER`, `TOKEN_ENV_VAR` and
    `PASSWORD_FIELD` are the *names* of places a credential lives, and flagging
    them as critical findings is the fastest way to get a linter uninstalled.
    """
    lowered = label.lower()
    if not SECRET_RE.search(lowered):
        return False
    return not lowered.endswith(SECRET_NAME_SUFFIXES)


def looks_like_secret_value(value: str) -> bool:
    """True when a literal string is shaped like a live credential.

    Four independent gates, because any one of them alone over-fires: a length
    floor, a charset the token formats actually use, at least two character
    classes (which rejects `user_password` and `MYAPP_TOKEN`), and a Shannon
    entropy floor (which rejects repeated or dictionary-ish text).
    """
    if len(value) < SECRET_MIN_LEN or len(value) > 512:
        return False
    lowered = value.lower()
    if lowered.startswith(SECRET_PLACEHOLDER_PREFIXES):
        return False
    if re.sub(r"[^a-z]", "", lowered) in SECRET_PLACEHOLDER_WORDS:
        return False
    if not SECRET_VALUE_RE.match(value):
        return False   # spaces, quotes, slashes: prose or a URL, not a token
    if _charset_classes(value) < 2:
        return False   # SCREAMING_SNAKE env-var names, snake_case field names
    return shannon_entropy(value) >= SECRET_MIN_ENTROPY


def looks_like_sql_statement(text: str) -> bool:
    """True when a string literal is the head of a real SQL statement.

    Requires a statement keyword at the *start* of the literal followed by the
    clause that keyword mandates, so 'update the cache for ' is not SQL while
    'UPDATE accounts SET balance = ' is. A lowercase head additionally needs a
    second clause keyword, because lowercase SQL verbs are ordinary English.
    """
    head_match = SQL_HEAD_RE.match(text)
    if not head_match:
        return False
    head, rest = head_match.group(1), head_match.group(2)
    required = SQL_REQUIRED_CLAUSE[head.lower()]
    if not re.search(required, rest, re.IGNORECASE):
        return False
    if head.isupper():
        return True
    return len(set(m.group(0).lower() for m in SQL_CLAUSE_RE.finditer(rest))) >= 2


def _complexity(fn: ast.AST) -> int:
    """Cyclomatic complexity: 1 + one per independent branch point."""
    score = 1
    for node in ast.walk(fn):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.BoolOp,
                             ast.IfExp, ast.Assert, ast.comprehension)):
            score += 1
        elif isinstance(node, ast.Match):
            score += len(node.cases)
    return score


_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _iter_own(node: ast.AST) -> Iterator[ast.AST]:
    """Yield descendants of `node` without descending into nested scopes.

    Rules such as unused-variable and inconsistent-return must not mix a
    closure's statements with its parent's, or they report phantom defects.
    """
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, _SCOPE_NODES):
            continue
        stack.extend(ast.iter_child_nodes(cur))


def _dotted(node: ast.AST) -> str:
    """Render an attribute/name chain as dotted text ('' when not a chain)."""
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def _terminates(body: list[ast.stmt]) -> bool:
    """True when every path through `body` ends in an explicit return/raise.

    Used by inconsistent-return: a function whose body terminates on all paths
    never implicitly returns None, so it is not inconsistent. The scan looks at
    every statement rather than only the last one, because anything following an
    unconditional exit is unreachable (dead-code reports that separately) and
    must not make the function look like it falls through.
    """
    for stmt in body:
        if isinstance(stmt, ast.Return):
            return stmt.value is not None
        if isinstance(stmt, ast.Raise):
            return True
        if isinstance(stmt, ast.If):
            if stmt.orelse and _terminates(stmt.body) and _terminates(stmt.orelse):
                return True
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            if _terminates(stmt.body):
                return True
        elif isinstance(stmt, ast.While):
            if isinstance(stmt.test, ast.Constant) and bool(stmt.test.value) \
                    and not any(isinstance(n, ast.Break) for n in ast.walk(stmt)):
                return True
        elif isinstance(stmt, ast.Try):
            handlers_ok = all(_terminates(h.body) for h in stmt.handlers)
            main = _terminates(stmt.orelse) if stmt.orelse else _terminates(stmt.body)
            if handlers_ok and main:
                return True
        elif isinstance(stmt, ast.Match):
            if stmt.cases and all(_terminates(c.body) for c in stmt.cases):
                return True
    return False


class _ModuleAnalysis:
    """Holds the per-module derived structures every pass needs.

    Building parents / scope maps once keeps the four passes O(nodes) instead of
    re-walking the tree for every rule.
    """

    def __init__(self, path: str, source: str, tree: ast.Module, cfg: AnalyzerConfig):
        self.path = path
        self.source = source
        self.lines = source.splitlines()
        self.tree = tree
        self.cfg = cfg
        self.findings: list[Finding] = []
        self.parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self.parents[child] = parent
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    # -- helpers ----------------------------------------------------------
    def enclosing_function(self, node: ast.AST) -> str:
        """Name of the nearest enclosing def, '' at module level."""
        cur = self.parents.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur.name
            cur = self.parents.get(cur)
        return ""

    def add(self, node_or_line: ast.AST | int, rule: str, message: str,
            suggestion: str) -> None:
        """Record a finding, pulling severity/category/why from the rule table."""
        if rule in self.cfg.skip_rules:
            return
        if isinstance(node_or_line, int):
            line, fn = node_or_line, ""
        else:
            line = getattr(node_or_line, "lineno", 1)
            fn = self.enclosing_function(node_or_line)
        spec = RULES[rule]
        self.findings.append(Finding(
            file=self.path, line=line, rule=rule, severity=spec.severity,
            message=message, suggestion=suggestion, category=spec.category,
            why=spec.why, function=fn))

    def in_with_items(self, call: ast.Call) -> bool:
        """True when the call is the context expression of a `with` statement."""
        return isinstance(self.parents.get(call), ast.withitem)

    def enclosing_scope(self, node: ast.AST) -> ast.AST:
        """Nearest enclosing def/lambda/class, falling back to the module."""
        cur = self.parents.get(node)
        while cur is not None:
            if isinstance(cur, _SCOPE_NODES):
                return cur
            cur = self.parents.get(cur)
        return self.tree

    def _resource_is_managed(self, call: ast.Call) -> bool:
        """True when this `open()` result has an owner that will close it.

        `with open(...)` is handled by the caller. This covers the four remaining
        shapes that are genuinely safe (or whose safety is somebody else's
        problem) and would otherwise be reported as leaks:

        * wrapped in `contextlib.closing(...)`, which the enclosing `with` closes;
        * assigned to a local that a later `.close()` in the same scope closes,
          which is the try/finally idiom;
        * stored on an attribute (`self.fh = open(...)`), so the object owns it;
        * returned or yielded, which hands ownership to the caller.
        """
        parent = self.parents.get(call)
        if isinstance(parent, ast.Call) and _dotted(parent.func).endswith("closing"):
            return True
        if isinstance(parent, (ast.Return, ast.Yield)):
            return True
        if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = (parent.targets if isinstance(parent, ast.Assign)
                       else [parent.target])
            names: list[str] = []
            for tgt in targets:
                if isinstance(tgt, ast.Name):
                    names.append(tgt.id)
                elif isinstance(tgt, ast.Attribute):
                    return True  # stored on an object; its lifetime owns the handle
            if names and self._closes_any(self.enclosing_scope(call), names):
                return True
        return False

    def _closes_any(self, scope: ast.AST, names: list[str]) -> bool:
        """True when `scope` calls `.close()` on one of `names` (try/finally idiom)."""
        wanted = {f"{name}.close" for name in names}
        for node in _iter_own(scope):
            if isinstance(node, ast.Call) and _dotted(node.func) in wanted:
                return True
        return False

    # -- pass 1: security --------------------------------------------------
    def pass_security(self) -> None:
        """Injection, credential and deserialization rules."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                self._security_call(node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                self._security_assign(node)
            elif isinstance(node, ast.Assert):
                self._security_assert(node)

    def _security_call(self, node: ast.Call) -> None:
        dotted = _dotted(node.func)
        name = dotted.rsplit(".", 1)[-1] if dotted else ""
        root = dotted.split(".")[0] if dotted else ""
        if name in ("eval", "exec") and not dotted.startswith("ast."):
            self.add(node, "eval-exec",
                     f"use of {name}() on a runtime value is a code-injection sink",
                     "replace with ast.literal_eval() or an explicit dispatch dict")
        if name in ("run", "call", "Popen", "check_output", "check_call"):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) \
                        and kw.value.value is True:
                    self.add(node, "shell-true",
                             "subprocess called with shell=True",
                             "pass an argument list (['git', 'clone', url]) and drop shell=True")
        if dotted in ("os.system", "os.popen"):
            self.add(node, "os-system", f"{dotted}() executes through the shell",
                     "use subprocess.run([...], shell=False) and check returncode")
        if (root, name) in DESERIALIZERS:
            self.add(node, "unsafe-deserialization",
                     f"{dotted}() rebuilds arbitrary objects from untrusted bytes",
                     "use json, or verify an HMAC over the payload before loading")
        if dotted in ("yaml.load", "yaml.full_load"):
            safe = any(kw.arg == "Loader" and "Safe" in _dotted(kw.value)
                       for kw in node.keywords)
            if not safe:
                self.add(node, "unsafe-deserialization",
                         "yaml.load() without SafeLoader can construct any Python object",
                         "call yaml.safe_load(), or pass Loader=yaml.SafeLoader")
        if dotted in ("hashlib.md5", "hashlib.sha1"):
            self.add(node, "weak-hash", f"{dotted}() is a broken hash function",
                     "use hashlib.sha256, or hmac/scrypt for secrets")
        if name in ("execute", "executemany", "executescript") and node.args:
            if self._is_built_sql(node.args[0]) and self._mentions_sql(node.args[0]):
                self.add(node, "sql-injection",
                         "SQL statement is assembled from a runtime value",
                         "use a parameterised query: execute(sql, (value,))")

    @staticmethod
    def _is_built_sql(arg: ast.expr) -> bool:
        """True when a query expression interpolates a value instead of binding it."""
        if isinstance(arg, ast.JoinedStr):
            return any(isinstance(v, ast.FormattedValue) for v in arg.values)
        if isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Add, ast.Mod)):
            return True
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) \
                and arg.func.attr == "format":
            return True
        return False

    def _security_assign(self, node: ast.Assign | ast.AnnAssign) -> None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        for tgt in targets:
            label = tgt.id if isinstance(tgt, ast.Name) else _dotted(tgt)
            if not label:
                continue
            if looks_like_secret_name(label) and isinstance(value, ast.Constant) \
                    and isinstance(value.value, str) \
                    and looks_like_secret_value(value.value):
                self.add(node, "hardcoded-secret",
                         f"'{label}' is assigned a literal credential-looking string",
                         "read it from os.environ / a secret manager and rotate this value")
            if value is not None and self._is_built_sql(value) \
                    and self._mentions_sql(value):
                self.add(node, "sql-injection",
                         f"'{label}' builds a SQL string by interpolation",
                         "keep the statement constant and pass values as parameters")

    @staticmethod
    def _mentions_sql(value: ast.expr) -> bool:
        """True when one of the literals in `value` is the head of a SQL statement."""
        return any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and looks_like_sql_statement(n.value) for n in ast.walk(value))

    def _security_assert(self, node: ast.Assert) -> None:
        fn = None
        cur = self.parents.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = cur
                break
            cur = self.parents.get(cur)
        if fn is None or fn.name.startswith("test_"):
            return
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
        uses_param = any(isinstance(n, ast.Name) and n.id in params
                         for n in ast.walk(node.test))
        if uses_param:
            self.add(node, "assert-validation",
                     f"assert validates argument(s) of '{fn.name}'",
                     "raise ValueError(...) so the check survives `python -O`")

    # -- pass 2: correctness ----------------------------------------------
    def pass_correctness(self) -> None:
        """Bug-pattern rules that do not depend on thresholds."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ExceptHandler):
                self._check_handler(node)
            elif isinstance(node, ast.Compare):
                self._check_is_literal(node)
            elif isinstance(node, ast.Call) and _dotted(node.func) == "open" \
                    and not self.in_with_items(node) \
                    and not self._resource_is_managed(node):
                self.add(node, "unclosed-resource",
                         "open() result is not managed by a `with` block",
                         "wrap it: `with open(path) as fh:` so it closes on any exit")
            elif isinstance(node, ast.For):
                self._check_off_by_one(node)
            elif isinstance(node, ast.Subscript):
                self._check_len_index(node)
        for fn in self.functions:
            self._check_mutable_default(fn)
            self._check_returns(fn)
            self._check_unused_and_shadowed(fn)

    def _check_handler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.add(node, "bare-except",
                     "bare `except:` catches KeyboardInterrupt and SystemExit too",
                     "catch the specific exceptions this block can actually handle")
            return
        caught = _dotted(node.type)
        body_is_noop = all(isinstance(s, (ast.Pass, ast.Expr)) for s in node.body)
        if caught in ("Exception", "BaseException") and body_is_noop:
            self.add(node, "broad-except",
                     f"`except {caught}` swallows every error without handling it",
                     "narrow the exception type, or log and re-raise")

    def _check_is_literal(self, node: ast.Compare) -> None:
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, (ast.Is, ast.IsNot)):
                continue
            for side in (node.left, comparator):
                if isinstance(side, ast.Constant) and side.value is not None \
                        and not isinstance(side.value, bool):
                    self.add(node, "is-literal",
                             f"`is` used to compare against the literal {side.value!r}",
                             "use == / != for value comparison; keep `is` for None")
                elif isinstance(side, (ast.Tuple, ast.List, ast.Dict, ast.Set)):
                    self.add(node, "is-literal",
                             "`is` used to compare against a freshly built container",
                             "use == : the literal is a new object every evaluation")

    def _check_off_by_one(self, node: ast.For) -> None:
        iter_call = node.iter
        if not (isinstance(iter_call, ast.Call) and _dotted(iter_call.func) == "range"):
            return
        # for i in range(1, len(x) + 1): -> the last index is out of range
        if len(iter_call.args) == 2 and isinstance(iter_call.args[1], ast.BinOp) \
                and isinstance(iter_call.args[1].op, ast.Add):
            hi = iter_call.args[1]
            if _dotted(getattr(hi.left, "func", hi.left)) == "len" \
                    and isinstance(hi.right, ast.Constant) and hi.right.value == 1:
                self.add(node, "off-by-one",
                         "range(1, len(seq) + 1) produces an index one past the end",
                         "iterate range(1, len(seq)) or enumerate(seq, 1) over values")
        if len(iter_call.args) != 1 or not isinstance(node.target, ast.Name):
            return
        inner = iter_call.args[0]
        if not (isinstance(inner, ast.Call) and _dotted(inner.func) == "len"
                and inner.args and isinstance(inner.args[0], ast.Name)):
            return
        seq, idx = inner.args[0].id, node.target.id
        for sub in _iter_own(node):
            if not (isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name)
                    and sub.value.id == seq):
                continue
            offset = sub.slice
            if isinstance(offset, ast.BinOp) and isinstance(offset.op, ast.Add) \
                    and isinstance(offset.left, ast.Name) and offset.left.id == idx \
                    and isinstance(offset.right, ast.Constant) \
                    and isinstance(offset.right.value, int) \
                    and not isinstance(offset.right.value, bool) \
                    and offset.right.value >= 1:
                self.add(sub, "off-by-one",
                         f"{seq}[{idx} + {offset.right.value}] reads past the end on the "
                         "last iteration",
                         f"stop the loop at range(len({seq}) - 1), or use "
                         f"zip({seq}, {seq}[1:])")

    def _check_len_index(self, node: ast.Subscript) -> None:
        if not isinstance(node.value, ast.Name):
            return
        idx = node.slice
        if isinstance(idx, ast.Call) and _dotted(idx.func) == "len" and idx.args \
                and isinstance(idx.args[0], ast.Name) \
                and idx.args[0].id == node.value.id:
            self.add(node, "off-by-one",
                     f"{node.value.id}[len({node.value.id})] is always out of range",
                     f"the last element is {node.value.id}[-1]")

    def _check_mutable_default(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for default in list(fn.args.defaults) + [d for d in fn.args.kw_defaults if d]:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                    isinstance(default, ast.Call)
                    and _dotted(default.func) in ("list", "dict", "set")):
                self.add(fn, "mutable-default",
                         f"function '{fn.name}' has a mutable default argument",
                         "default to None and build the container inside the function")

    def _check_returns(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        returns = [n for n in _iter_own(fn) if isinstance(n, ast.Return)]
        if not returns:
            return
        valued = [r for r in returns if r.value is not None]
        bare = [r for r in returns if r.value is None]
        if not valued:
            return
        if bare:
            self.add(bare[0], "inconsistent-return",
                     f"'{fn.name}' mixes `return <value>` with a bare `return`",
                     "return an explicit sentinel (None / empty tuple) on every path")
        elif not _terminates(fn.body):
            self.add(fn, "inconsistent-return",
                     f"'{fn.name}' returns a value on some paths and falls through "
                     "to an implicit None on others",
                     "add a final `return` with an explicit value, or raise")

    def _check_unused_and_shadowed(
            self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        owned = list(_iter_own(fn))
        if any(isinstance(n, ast.Call) and _dotted(n.func) in ("locals", "vars", "eval")
               for n in owned):
            return  # dynamic scope access defeats static liveness
        declared: set[str] = set()
        for n in owned:
            if isinstance(n, (ast.Global, ast.Nonlocal)):
                declared.update(n.names)
        # Loads are collected from the whole subtree, not just this scope: a
        # closure defined here still reads its enclosing function's locals, and
        # ignoring that produced phantom "assigned but never read" reports.
        loaded = {n.id for n in ast.walk(fn)
                  if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Store)}
        for arg in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs:
            if arg.arg in SHADOWABLE_BUILTINS:
                self.add(fn, "shadowed-builtin",
                         f"parameter '{arg.arg}' shadows the builtin of the same name",
                         f"rename it (e.g. '{arg.arg}_' or a domain word)")
        simple_targets: dict[str, int] = {}
        for n in owned:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                    and isinstance(n.targets[0], ast.Name):
                simple_targets.setdefault(n.targets[0].id, n.lineno)
        for name, line in sorted(simple_targets.items(), key=lambda kv: kv[1]):
            if name in SHADOWABLE_BUILTINS:
                self.add(line, "shadowed-builtin",
                         f"local '{name}' shadows the builtin of the same name",
                         f"rename the local; later calls to {name}() in this scope break")
            if name.startswith("_") or name in declared or name in loaded:
                continue
            self.add(line, "unused-variable",
                     f"local '{name}' is assigned but never read",
                     "remove it, or use it - the computed value is being discarded")

    # -- pass 3: complexity ------------------------------------------------
    def pass_complexity(self) -> None:
        """Threshold rules over per-function and per-module size metrics."""
        cfg = self.cfg
        for fn in self.functions:
            comp = _complexity(fn)
            if comp > cfg.max_complexity:
                self.add(fn, "high-complexity",
                         f"'{fn.name}' cyclomatic complexity {comp} (max {cfg.max_complexity})",
                         "extract the branch bodies into named helpers and use early returns")
            depth = nesting_depth(fn)
            if depth > cfg.max_nesting:
                self.add(fn, "deep-nesting",
                         f"'{fn.name}' nests control flow {depth} levels deep "
                         f"(max {cfg.max_nesting})",
                         "invert conditions to return early, or extract the inner loop")
            length = (getattr(fn, "end_lineno", fn.lineno) or fn.lineno) - fn.lineno + 1
            if length > cfg.max_fn_lines:
                self.add(fn, "long-function",
                         f"'{fn.name}' is {length} lines (max {cfg.max_fn_lines})",
                         "split it along its comment headings into separate functions")
            n_params = len(fn.args.args) + len(fn.args.kwonlyargs) + len(fn.args.posonlyargs)
            if n_params > cfg.max_params:
                self.add(fn, "too-many-params",
                         f"'{fn.name}' takes {n_params} parameters (max {cfg.max_params})",
                         "group the related ones into a dataclass or config object")
        roots = module_imports(self.tree)
        if len(roots) > cfg.max_imports:
            self.add(1, "high-coupling",
                     f"module imports {len(roots)} distinct top-level modules "
                     f"(max {cfg.max_imports})",
                     "split the module by responsibility so each part has few dependencies")

    # -- pass 4: maintainability ------------------------------------------
    def pass_maintainability(self) -> None:
        """Docstrings, dead code, unused imports and textual hygiene."""
        cfg = self.cfg
        for i, text in enumerate(self.lines, 1):
            if len(text) > cfg.max_line_len:
                self.add(i, "long-line",
                         f"line is {len(text)} characters (max {cfg.max_line_len})",
                         "wrap the expression or extract a named intermediate")
            if TODO_RE.search(text):
                self.add(i, "todo-marker", text.strip()[:90],
                         "file an issue and link it, or delete the note")
        if ast.get_docstring(self.tree) is None:
            self.add(1, "missing-docstring", "module has no docstring",
                     "add a one-line module docstring describing its responsibility")
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                    and not node.name.startswith("_") \
                    and ast.get_docstring(node) is None \
                    and isinstance(self.parents.get(node), (ast.Module, ast.ClassDef)):
                # Only module-level defs and methods are API; a closure defined
                # inside a function is an implementation detail.
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                self.add(node, "missing-docstring",
                         f"public {kind} '{node.name}' lacks a docstring",
                         "document what it returns and which errors it raises")
            self._check_dead_code(node)
        self._check_imports()

    def _check_dead_code(self, node: ast.AST) -> None:
        for field_name in ("body", "orelse", "finalbody"):
            block = getattr(node, field_name, None)
            if not isinstance(block, list):
                continue
            for i, stmt in enumerate(block[:-1]):
                if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                    nxt = block[i + 1]
                    self.add(nxt, "dead-code",
                             f"statement is unreachable: the preceding "
                             f"{type(stmt).__name__.lower()} always exits this block",
                             "delete it, or move it above the exit statement")
                    break
        if isinstance(node, (ast.If, ast.While)) and isinstance(node.test, ast.Constant) \
                and node.test.value is False:
            self.add(node, "dead-code", "condition is a constant False",
                     "remove the block, or restore the real condition")

    def _check_imports(self) -> None:
        imported: dict[str, int] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported[(alias.asname or alias.name).split(".")[0]] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                if node.module == "__future__":
                    continue  # compiler directives have no runtime reference
                for alias in node.names:
                    if alias.name != "*":
                        imported[alias.asname or alias.name] = node.lineno
        used: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                root = _dotted(node).split(".")[0]
                if root:
                    used.add(root)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                used.update(re.findall(r"\w+", node.value))  # names used in annotations
        exported = self._dunder_all()
        for name, line in sorted(imported.items(), key=lambda kv: (kv[1], kv[0])):
            if name not in used and name not in exported:
                self.add(line, "unused-import", f"import '{name}' is never used",
                         "remove the import")
        module_privates = {n.name: n.lineno for n in self.tree.body
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and n.name.startswith("_") and not n.name.startswith("__")}
        for name, line in sorted(module_privates.items(), key=lambda kv: kv[1]):
            refs = sum(1 for n in ast.walk(self.tree)
                       if isinstance(n, ast.Name) and n.id == name)
            if refs == 0:
                self.add(line, "unused-private",
                         f"private helper '{name}' is never called in this module",
                         "delete it, or make it public if other modules need it")

    def _dunder_all(self) -> set[str]:
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                return {el.value for el in getattr(node.value, "elts", [])
                        if isinstance(el, ast.Constant) and isinstance(el.value, str)}
        return set()


def nesting_depth(node: ast.AST) -> int:
    """Maximum nesting depth of control-flow blocks inside a function."""
    nesting_types = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With,
                     ast.AsyncWith, ast.Try)

    def walk(n: ast.AST, depth: int) -> int:
        best = depth
        for child in ast.iter_child_nodes(n):
            if isinstance(child, _SCOPE_NODES):
                continue
            nxt = depth + 1 if isinstance(child, nesting_types) else depth
            best = max(best, walk(child, nxt))
        return best

    return walk(node, 0)


def module_imports(tree: ast.Module) -> set[str]:
    """Set of distinct top-level modules this module depends on (coupling metric)."""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def analyze_source(path: str, source: str, config: AnalyzerConfig | None = None,
                   tree: ast.Module | None = None) -> list[Finding]:
    """Run all four passes over one module and return findings sorted by location."""
    cfg = config or AnalyzerConfig()
    if tree is None:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            spec = RULES["syntax-error"]
            return [Finding(path, exc.lineno or 1, "syntax-error", spec.severity,
                            f"module does not parse: {exc.msg}",
                            "fix the syntax error before reviewing the logic",
                            spec.category, spec.why)]
    analysis = _ModuleAnalysis(path, source, tree, cfg)
    analysis.pass_security()
    analysis.pass_correctness()
    analysis.pass_complexity()
    analysis.pass_maintainability()
    unique: dict[tuple, Finding] = {}
    for finding in analysis.findings:
        unique.setdefault(finding.key, finding)
    return sorted(unique.values(),
                  key=lambda f: (f.line, SEVERITY_ORDER[f.severity], f.rule))
