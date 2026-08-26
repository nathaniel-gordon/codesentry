"""End-to-end entry points shared by the CLI and the smoke test.

Keeping the orchestration here (rather than in `cli.py`) means the tests exercise
exactly the code path the CLI runs, including the agent loop.
"""
from __future__ import annotations

import os

from .agent import build_agent
from .analyzers import AnalyzerConfig
from .diffing import (DiffStat, changed_lines_between, iter_python_files,
                      parse_unified_diff)
from .review import ReviewResult, ReviewSession


def review_repo(root: str, planner: str = "auto", config: AnalyzerConfig | None = None,
                files: list[str] | None = None,
                changed: dict[str, set[int]] | None = None,
                diff_stat: DiffStat | None = None, scope: str = "line",
                context: int = 0) -> tuple[ReviewResult, str]:
    """Run the agent over `root` and return (result, planner-used).

    The agent drives the session; `finalize` then ranks, optionally diff-filters
    and scores whatever the agent gathered.
    """
    session = ReviewSession(root, config=config, files=files)
    agent, used = build_agent(session, planner=planner)
    goal = (f"Review the Python repository at {root}: analyze every file for "
            "security, correctness, complexity and maintainability defects, find "
            "duplicated logic, and check configuration files for credentials.")
    agent.run(goal)
    result = session.finalize(trace=agent.trace_report(), changed=changed,
                              diff_stat=diff_stat, scope=scope, context=context)
    return result, used


def review_diff(base_root: str, head_root: str, planner: str = "auto",
                config: AnalyzerConfig | None = None, scope: str = "line",
                context: int = 0) -> tuple[ReviewResult, str]:
    """Review only what changed between two directory snapshots."""
    changed, stat = changed_lines_between(base_root, head_root)
    files = sorted(set(iter_python_files(head_root)) & set(changed)) or None
    return review_repo(head_root, planner=planner, config=config, files=files,
                       changed=changed, diff_stat=stat, scope=scope, context=context)


def review_patch(root: str, diff_path: str, planner: str = "auto",
                 config: AnalyzerConfig | None = None, scope: str = "line",
                 context: int = 0) -> tuple[ReviewResult, str]:
    """Review a working tree restricted to the lines a unified diff file touches."""
    with open(diff_path, "r", encoding="utf-8", errors="replace") as handle:
        changed, stat = parse_unified_diff(handle.read())
    present = set(iter_python_files(root))
    changed = {k: v for k, v in changed.items() if k in present}
    files = sorted(changed) or None
    return review_repo(root, planner=planner, config=config, files=files,
                       changed=changed, diff_stat=stat, scope=scope, context=context)


def default_output_dir() -> str:
    """`output/` next to the project root, created on demand."""
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "output")
    os.makedirs(out, exist_ok=True)
    return out
