"""Cross-file copy-paste detection via token-shingle similarity over AST shape.

Text diffing misses copy-paste as soon as someone renames the variables, so the
comparison runs over a *structural* token stream: every node contributes its type
(and operators contribute their kind), while identifiers and literals collapse to
a single placeholder. Two blocks that differ only in naming therefore produce
identical streams.

Candidate pairs come from an inverted shingle index, so the cost is proportional
to the number of functions that actually share structure rather than to N^2.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass

from .analyzers import RULES, Finding

_PLACEHOLDER = {ast.Name: "N", ast.Constant: "C", ast.arg: "A", ast.Attribute: "T"}


@dataclass
class CodeBlock:
    """A named block (function) reduced to its structural token stream."""

    file: str
    name: str
    line: int
    end_line: int
    tokens: tuple[str, ...]

    def shingles(self, k: int) -> set[tuple[str, ...]]:
        """k-length sliding windows over the token stream."""
        if len(self.tokens) < k:
            return set()
        return {self.tokens[i:i + k] for i in range(len(self.tokens) - k + 1)}


@dataclass
class DuplicatePair:
    """Two blocks whose structure overlaps above the similarity threshold."""

    a: CodeBlock
    b: CodeBlock
    similarity: float

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {
            "similarity": round(self.similarity, 3),
            "a": {"file": self.a.file, "name": self.a.name, "line": self.a.line},
            "b": {"file": self.b.file, "name": self.b.name, "line": self.b.line},
        }


def _shape_tokens(node: ast.AST) -> list[str]:
    """Preorder structural tokens: node types with identifiers/literals erased."""
    out: list[str] = []

    def visit(n: ast.AST) -> None:
        placeholder = _PLACEHOLDER.get(type(n))
        out.append(placeholder or type(n).__name__)
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.Load, ast.Store, ast.Del)):
                continue
            visit(child)

    for stmt in getattr(node, "body", []):
        visit(stmt)
    return out


def extract_blocks(file: str, tree: ast.Module) -> list[CodeBlock]:
    """Module-level functions and methods, reduced to structural tokens.

    Closures are deliberately excluded: a nested function's tokens are already
    part of its parent's stream, so comparing both reports every factory
    function as a clone of the function it returns.
    """
    blocks: list[CodeBlock] = []

    def take(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        end = node.end_lineno or node.lineno
        blocks.append(CodeBlock(file, node.name, node.lineno, end,
                                tuple(_shape_tokens(node))))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            take(node)
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    take(member)
    return blocks


def find_duplicates(blocks: list[CodeBlock], *, k: int = 6, min_tokens: int = 35,
                    threshold: float = 0.85) -> list[DuplicatePair]:
    """Return block pairs with Jaccard shingle similarity >= threshold.

    `min_tokens` keeps small idiomatic helpers (a guard plus a return) from being
    reported as clones of each other, which is the usual source of false
    positives in copy-paste detectors.
    """
    sized = [b for b in blocks if len(b.tokens) >= min_tokens]
    sized.sort(key=lambda b: (b.file, b.line))
    shingle_sets = {id(b): b.shingles(k) for b in sized}
    index: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for i, block in enumerate(sized):
        for sh in shingle_sets[id(block)]:
            index[sh].append(i)
    candidates: set[tuple[int, int]] = set()
    for holders in index.values():
        if len(holders) < 2 or len(holders) > 40:
            continue  # a shingle shared by everything carries no information
        for a_i in range(len(holders)):
            for b_i in range(a_i + 1, len(holders)):
                candidates.add((holders[a_i], holders[b_i]))
    pairs: list[DuplicatePair] = []
    for i, j in sorted(candidates):
        sa, sb = shingle_sets[id(sized[i])], shingle_sets[id(sized[j])]
        union = len(sa | sb)
        if not union:
            continue
        sim = len(sa & sb) / union
        if sim >= threshold:
            pairs.append(DuplicatePair(sized[i], sized[j], sim))
    pairs.sort(key=lambda p: (-p.similarity, p.a.file, p.a.line))
    return pairs


def duplicate_findings(pairs: list[DuplicatePair]) -> list[Finding]:
    """Turn duplicate pairs into findings anchored at the later copy."""
    spec = RULES["duplicate-block"]
    out: list[Finding] = []
    for pair in pairs:
        first, second = sorted((pair.a, pair.b), key=lambda b: (b.file, b.line))
        out.append(Finding(
            file=second.file, line=second.line, rule="duplicate-block",
            severity=spec.severity, category=spec.category, why=spec.why,
            message=(f"'{second.name}' is {pair.similarity:.0%} structurally identical "
                     f"to '{first.name}' at {first.file}:{first.line}"),
            suggestion=("extract the shared logic into one function and call it from "
                        "both sites"),
            function=second.name))
    return out
