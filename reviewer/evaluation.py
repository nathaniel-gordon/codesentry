"""Score a review against the demo repo's ground truth.

Recall alone is easy to game (report everything), so precision is measured too -
but only where it can be measured honestly. Files the generator wrote to be
benign are the negative corpus: any finding on one of them is a false positive
by construction, because nothing defective was written there. Findings on a file
that *does* contain planted defects are not counted either way, since the
generator never claimed those files were otherwise clean.

That is the whole basis for the per-rule table `codesentry eval` prints. It is a
measurement on a synthetic corpus and nothing more; it does not predict how the
rules behave on real code.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .analyzers import RULES, Finding
from .datagen import DemoManifest, Plant


@dataclass
class EvalResult:
    """Recall against planted defects plus precision on the clean files."""

    planted: int
    matched: list[Plant] = field(default_factory=list)
    missed: list[Plant] = field(default_factory=list)
    clean_files: tuple[str, ...] = ()
    clean_findings: list[Finding] = field(default_factory=list)
    category_recall: dict[str, tuple[int, int]] = field(default_factory=dict)
    extra_findings: int = 0

    @property
    def recall(self) -> float:
        """Fraction of planted defects reported at the exact file:line:rule."""
        return len(self.matched) / self.planted if self.planted else 0.0

    @property
    def clean_precision(self) -> float:
        """1.0 when no clean file produced a finding; degrades per false positive."""
        if not self.clean_files:
            return 1.0
        dirty = {f.file for f in self.clean_findings}
        return 1.0 - len(dirty) / len(self.clean_files)

    def summary(self) -> str:
        """One-line human summary used by the demo and the smoke test."""
        return (f"recall {self.recall:.0%} ({len(self.matched)}/{self.planted} planted "
                f"defects at exact file:line), clean-file precision "
                f"{self.clean_precision:.0%} ({len(self.clean_findings)} findings on "
                f"{len(self.clean_files)} clean files)")

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {
            "planted": self.planted,
            "matched": len(self.matched),
            "recall": round(self.recall, 4),
            "missed": [p.to_dict() for p in self.missed],
            "clean_files": list(self.clean_files),
            "clean_findings": [f.to_dict() for f in self.clean_findings],
            "clean_precision": round(self.clean_precision, 4),
            "category_recall": {k: list(v) for k, v in self.category_recall.items()},
            "unplanted_findings": self.extra_findings,
        }


@dataclass(frozen=True)
class RuleScore:
    """Per-rule confusion counts on the corpus.

    `fp` counts only findings on the benign files, which is the sole place a
    false positive is provable. A rule with no plant and no benign hit scores
    zero across the board and is reported as unmeasured rather than as perfect.
    """

    rule: str
    tp: int
    fp: int
    fn: int

    @property
    def measured(self) -> bool:
        """False when the corpus exercises this rule neither way."""
        return bool(self.tp or self.fp or self.fn)

    @property
    def precision(self) -> float:
        """TP / (TP + FP), or 0.0 when the rule never fired."""
        total = self.tp + self.fp
        return self.tp / total if total else 0.0

    @property
    def recall(self) -> float:
        """TP / (TP + FN), or 0.0 when nothing was planted for this rule."""
        total = self.tp + self.fn
        return self.tp / total if total else 0.0

    @property
    def f1(self) -> float:
        """Harmonic mean of precision and recall."""
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {"rule": self.rule, "tp": self.tp, "fp": self.fp, "fn": self.fn,
                "precision": round(self.precision, 4),
                "recall": round(self.recall, 4), "f1": round(self.f1, 4),
                "measured": self.measured}


def rule_scores(findings: list[Finding], manifest: DemoManifest) -> list[RuleScore]:
    """Per-rule TP/FP/FN, ordered by rule id; unmeasured rules are omitted."""
    reported = {f.key for f in findings}
    benign = set(manifest.clean_files)
    scores: list[RuleScore] = []
    for rule in sorted(RULES):
        planted = [p for p in manifest.plants if p.rule == rule]
        tp = sum(1 for p in planted if p.key in reported)
        fn = len(planted) - tp
        fp = sum(1 for f in findings if f.rule == rule and f.file in benign)
        score = RuleScore(rule=rule, tp=tp, fp=fp, fn=fn)
        if score.measured:
            scores.append(score)
    return scores


def evaluate(findings: list[Finding], manifest: DemoManifest) -> EvalResult:
    """Compare a review's findings with the manifest of deliberately planted defects."""
    reported = {f.key for f in findings}
    matched = [p for p in manifest.plants if p.key in reported]
    missed = [p for p in manifest.plants if p.key not in reported]
    clean = set(manifest.clean_files)
    clean_findings = [f for f in findings if f.file in clean]
    per_category: dict[str, tuple[int, int]] = {}
    for plant in manifest.plants:
        hit, total = per_category.get(plant.category, (0, 0))
        per_category[plant.category] = (hit + (1 if plant.key in reported else 0),
                                        total + 1)
    planted_keys = {p.key for p in manifest.plants}
    extra = sum(1 for f in findings if f.key not in planted_keys)
    return EvalResult(planted=len(manifest.plants), matched=matched, missed=missed,
                      clean_files=manifest.clean_files, clean_findings=clean_findings,
                      category_recall=dict(sorted(per_category.items())),
                      extra_findings=extra)
