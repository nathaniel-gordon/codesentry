"""The default review path: four straight steps, no planner in between.

`review_repo` used to build an agent and run a plan/act/observe loop for every
review, including a pre-commit hook on two staged files. The loop's deterministic
policy was a hardcoded if/elif sequence reproducing exactly the order below, and
its exception handler turned an analyzer crash into a trace string, so a broken
rule looked like a clean file.

The agent still exists and is still driven by real tools, but it is now
`--mode agent`: a demonstration of the same capabilities under a planner, not
the mandatory execution path.
"""
from __future__ import annotations

import time

from .errors import AnalysisError, ToolInputError
from .logging_setup import get_logger
from .review import ReviewSession
from .telemetry import PHASE_DURATION, REGISTRY, RUN_DURATION

log = get_logger("scan")


def analyze_repo(session: ReviewSession, *, duplicates: bool = True,
                 secrets: bool = True) -> str:
    """Run the review over `session` and return a short human summary.

    Steps, in order: analyze every discovered file; detect cross-file clones
    (which needs every AST parsed first); search non-Python files for
    credentials the AST passes cannot see. Per-file analyzer failures are
    collected on the session rather than aborting the walk, and they make the
    run exit non-zero.
    """
    started = time.perf_counter()
    log.info("review started", extra={"root": session.root,
                                      "files": len(session.files)})
    with REGISTRY.timed(PHASE_DURATION, phase="analyze"):
        session.analyze_all()
    pairs = 0
    if duplicates:
        with REGISTRY.timed(PHASE_DURATION, phase="duplicates"):
            session.scan_duplicates()
        pairs = len(session.duplicate_pairs)
    for rel in list(session.sources):
        session.release(rel)
    recorded = 0
    if secrets:
        try:
            with REGISTRY.timed(PHASE_DURATION, phase="secrets"):
                recorded = session.scan_secrets()
        except ToolInputError as exc:
            session.errors.append(AnalysisError(str(exc), file="<secret-scan>"))
    elapsed = (time.perf_counter() - started) * 1000
    REGISTRY.observe(RUN_DURATION, elapsed)
    log.info("review finished", extra={
        "files": len(session.metrics), "findings": len(session.findings),
        "errors": len(session.errors), "elapsed_ms": round(elapsed, 1),
        "cache_hits": session.cache_hits, "cache_misses": session.cache_misses})
    return (f"analyzed {len(session.metrics)} file(s), {len(session.findings)} "
            f"finding(s), {pairs} duplicate pair(s), {recorded} config credential(s), "
            f"{len(session.errors)} analyzer error(s) in {elapsed:.0f}ms")
