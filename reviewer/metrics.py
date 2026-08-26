"""Per-function and per-module size metrics used for risk ranking and reporting.

The analyzers emit *findings*; this module emits *measurements*. Keeping them
apart matters because risk ranking multiplies a finding's severity by the
complexity of the code it sits in, which needs the numbers even when no
complexity rule fired.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .analyzers import _complexity, module_imports, nesting_depth


@dataclass
class FunctionMetrics:
    """Size and shape of a single function."""

    file: str
    name: str
    line: int
    end_line: int
    complexity: int
    nesting: int
    length: int
    params: int
    has_docstring: bool
    is_public: bool

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {
            "file": self.file, "name": self.name, "line": self.line,
            "end_line": self.end_line, "complexity": self.complexity,
            "nesting": self.nesting, "length": self.length,
            "params": self.params, "has_docstring": self.has_docstring,
            "is_public": self.is_public,
        }


@dataclass
class ModuleMetrics:
    """Aggregate shape of one source file."""

    file: str
    loc: int
    sloc: int
    functions: list[FunctionMetrics] = field(default_factory=list)
    classes: int = 0
    imports: tuple[str, ...] = ()
    parse_ok: bool = True

    @property
    def coupling(self) -> int:
        """Number of distinct top-level modules this file depends on."""
        return len(self.imports)

    @property
    def max_complexity(self) -> int:
        """Highest cyclomatic complexity in the file (0 when it has no functions)."""
        return max((f.complexity for f in self.functions), default=0)

    @property
    def avg_complexity(self) -> float:
        """Mean cyclomatic complexity across the file's functions."""
        if not self.functions:
            return 0.0
        return sum(f.complexity for f in self.functions) / len(self.functions)

    @property
    def doc_coverage(self) -> float:
        """Fraction of public functions carrying a docstring (1.0 when none exist)."""
        public = [f for f in self.functions if f.is_public]
        if not public:
            return 1.0
        return sum(1 for f in public if f.has_docstring) / len(public)

    def complexity_at(self, line: int) -> int:
        """Complexity of the function containing `line`, else the file average.

        Risk ranking uses this: a critical bug inside a 30-branch function is
        harder to fix safely than the same bug in a three-line helper.
        """
        best = 0
        for fn in self.functions:
            if fn.line <= line <= fn.end_line:
                best = max(best, fn.complexity)
        if best:
            return best
        return int(round(self.avg_complexity))

    def function_at(self, line: int) -> FunctionMetrics | None:
        """Innermost function containing `line`, or None at module level."""
        best: FunctionMetrics | None = None
        for fn in self.functions:
            if fn.line <= line <= fn.end_line:
                if best is None or fn.line > best.line:
                    best = fn
        return best

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view including derived properties."""
        return {
            "file": self.file, "loc": self.loc, "sloc": self.sloc,
            "classes": self.classes, "coupling": self.coupling,
            "imports": sorted(self.imports),
            "max_complexity": self.max_complexity,
            "avg_complexity": round(self.avg_complexity, 2),
            "doc_coverage": round(self.doc_coverage, 3),
            "functions": [f.to_dict() for f in self.functions],
            "parse_ok": self.parse_ok,
        }


def _sloc(source: str) -> int:
    """Count source lines that are neither blank nor comment-only."""
    total = 0
    for raw in source.splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            total += 1
    return total


def module_metrics(path: str, source: str, tree: ast.Module | None = None) -> ModuleMetrics:
    """Measure one module; returns a parse_ok=False shell when it does not compile."""
    loc = len(source.splitlines())
    if tree is None:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            return ModuleMetrics(path, loc, _sloc(source), parse_ok=False)
    fns: list[FunctionMetrics] = []
    classes = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            fns.append(FunctionMetrics(
                file=path, name=node.name, line=node.lineno, end_line=end,
                complexity=_complexity(node), nesting=nesting_depth(node),
                length=end - node.lineno + 1,
                params=len(node.args.args) + len(node.args.kwonlyargs)
                + len(node.args.posonlyargs),
                has_docstring=ast.get_docstring(node) is not None,
                is_public=not node.name.startswith("_")))
    fns.sort(key=lambda f: f.line)
    return ModuleMetrics(path, loc, _sloc(source), fns, classes,
                         tuple(sorted(module_imports(tree))))
