"""End-to-end entry points shared by the CLI, the Action and the tests.

Keeping orchestration here means the tests exercise exactly the path the CLI
runs. Two execution modes go through the same `ReviewSession` and produce the
same `ReviewResult`:

    mode="direct"  four straight steps (the default; see `scan.analyze_repo`)
    mode="agent"   the plan/act/observe loop over the same tools
"""
from __future__ import annotations

import os

from .analyzers import AnalyzerConfig
from .cache import AnalysisCache
from .diffing import (DiffStat, changed_lines_between, iter_python_files,
                      parse_unified_diff)
from .errors import InputError
from .logging_setup import get_logger
from .review import ReviewResult, ReviewSession
from .scan import analyze_repo
from .suppression import Suppressions

log = get_logger("pipeline")


def review_repo(root: str, mode: str = "direct", planner: str = "auto",
                config: AnalyzerConfig | None = None,
                files: list[str] | None = None,
                changed: dict[str, set[int]] | None = None,
                diff_stat: DiffStat | None = None, scope: str = "line",
                context: int = 0, cache: AnalysisCache | None = None,
                suppressions: Suppressions | None = None) -> tuple[ReviewResult, str]:
    """Review `root` and return (result, the engine actually used).

    The engine string is what ran, not what was asked for: `--planner llm`
    without credentials degrades to the deterministic planner, and that has to
    be visible in the report rather than assumed.
    """
    session = ReviewSession(root, config=config, files=files,
                            suppressions=suppressions, cache=cache)
    if mode == "agent":
        from .agent import build_agent
        agent, used = build_agent(session, planner=planner)
        goal = (f"Review the Python repository at {root}: analyze every file for "
                "security, correctness, complexity and maintainability defects, "
                "find duplicated logic, and check configuration files for "
                "credentials.")
        agent.run(goal)
        trace = agent.trace_report()
        engine = f"agent:{used}"
    else:
        trace = analyze_repo(session)
        engine = "direct"
    result = session.finalize(trace=trace, changed=changed, diff_stat=diff_stat,
                              scope=scope, context=context)
    return result, engine


def review_diff(base_root: str, head_root: str, mode: str = "direct",
                planner: str = "auto", config: AnalyzerConfig | None = None,
                scope: str = "line", context: int = 0,
                cache: AnalysisCache | None = None,
                suppressions: Suppressions | None = None) -> tuple[ReviewResult, str]:
    """Review only what changed between two directory snapshots."""
    for label, path in (("base", base_root), ("head", head_root)):
        if not os.path.isdir(path):
            raise InputError(f"--{label} is not a directory", path=path)
    changed, stat = changed_lines_between(base_root, head_root)
    files = sorted(set(iter_python_files(head_root)) & set(changed)) or None
    return review_repo(head_root, mode=mode, planner=planner, config=config,
                       files=files, changed=changed, diff_stat=stat, scope=scope,
                       context=context, cache=cache, suppressions=suppressions)


def review_patch(root: str, diff_path: str, mode: str = "direct",
                 planner: str = "auto", config: AnalyzerConfig | None = None,
                 scope: str = "line", context: int = 0,
                 cache: AnalysisCache | None = None,
                 suppressions: Suppressions | None = None) -> tuple[ReviewResult, str]:
    """Review a working tree restricted to the lines a unified diff file touches.

    Paths in the diff are attacker-controlled text, so they are intersected with
    the files actually discovered under `root` and never used to open anything
    directly.
    """
    try:
        with open(diff_path, "r", encoding="utf-8", errors="replace") as handle:
            changed, stat = parse_unified_diff(handle.read())
    except OSError as exc:
        raise InputError(f"cannot read patch: {exc}", path=diff_path) from exc
    present = set(iter_python_files(root))
    dropped = sorted(set(changed) - present)
    if dropped:
        log.info("patch names files outside the review root",
                 extra={"dropped": len(dropped)})
    changed = {k: v for k, v in changed.items() if k in present}
    files = sorted(changed) or None
    return review_repo(root, mode=mode, planner=planner, config=config, files=files,
                       changed=changed, diff_stat=stat, scope=scope, context=context,
                       cache=cache, suppressions=suppressions)


def default_output_dir() -> str:
    """`output/` next to the project root, created on demand."""
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "output")
    os.makedirs(out, exist_ok=True)
    return out
