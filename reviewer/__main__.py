"""Autonomous Multi-Pass Python Code Review Agent — Module Entry Point.

Usage
-----
    python -m reviewer demo          # generate planted defect repo and evaluate recall
    python -m reviewer review <path> # full repository or file review
    python -m reviewer diff          # review only changed lines in diff
    python -m reviewer metrics <dir> # function complexity metrics
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from tabulate import tabulate

from .analyzers import SEVERITY_ORDER, AnalyzerConfig
from .datagen import write_demo_pair
from .evaluation import evaluate
from .pipeline import default_output_dir, review_diff, review_patch, review_repo
from .report import write_reports
from .review import ReviewResult

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config(args: argparse.Namespace) -> AnalyzerConfig:
    return AnalyzerConfig(
        max_complexity=args.max_complexity,
        max_nesting=args.max_nesting,
        max_fn_lines=args.max_fn_lines,
        max_params=args.max_params,
        max_line_len=args.max_line_len,
        max_imports=args.max_imports,
    )


def _add_threshold_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-complexity", type=int, default=10)
    parser.add_argument("--max-nesting", type=int, default=4)
    parser.add_argument("--max-fn-lines", type=int, default=60)
    parser.add_argument("--max-params", type=int, default=6)
    parser.add_argument("--max-line-len", type=int, default=110)
    parser.add_argument("--max-imports", type=int, default=12)
    parser.add_argument(
        "--planner",
        choices=("auto", "rules", "llm"),
        default="auto",
        help="'llm' uses Claude to plan the investigation when ANTHROPIC_API_KEY is set; otherwise rules are used",
    )


def _severity_table(result: ReviewResult) -> str:
    rows = [[sev, result.by_severity[sev]] for sev in SEVERITY_ORDER]
    return tabulate(rows, headers=["severity", "count"], tablefmt="github")


def _top_risk_table(result: ReviewResult, limit: int = 8) -> str:
    rows = [
        [f"{f.risk:.1f}", f.severity, f.location(), f.rule, f.message[:64]]
        for f in result.top_risks(limit)
    ]
    return tabulate(
        rows,
        headers=["risk", "severity", "location", "rule", "message"],
        tablefmt="github",
    )


def _print_result(result: ReviewResult, planner: str, label: str) -> None:
    print(f"\n{label}")
    print("-" * len(label))
    print(
        f"planner={planner}  files={len(result.metrics)}  sloc={result.total_sloc}  "
        f"churn={result.churn.source}  findings={len(result.findings)}"
    )
    print(f"health score: {result.health.score:.1f}/100 (grade {result.health.grade})")
    print(_severity_table(result))
    if result.findings:
        print("\ntop risks (severity x complexity x churn):")
        print(_top_risk_table(result))


def cmd_demo(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    out_dir = default_output_dir()
    demo_dir = os.path.join(out_dir, "demo_repo")
    if os.path.isdir(demo_dir):
        shutil.rmtree(demo_dir, ignore_errors=True)
    base_manifest, head_manifest = write_demo_pair(demo_dir, seed=args.seed)
    base_root = os.path.join(demo_dir, "base")
    head_root = os.path.join(demo_dir, "head")
    print("=" * 78)
    print("AUTONOMOUS CODE REVIEW AGENT - forward-chaining rules demo")
    print("=" * 78)
    print(f"generated demo repo: {base_root}")
    print(
        f"  {len(base_manifest.files)} files, "
        f"{len(base_manifest.plants)} deliberately planted defects, "
        f"{len(base_manifest.clean_files)} files written to be clean"
    )

    config = _config(args)
    result, planner = review_repo(base_root, planner=args.planner, config=config)
    _print_result(result, planner, "FULL REPO REVIEW")

    print("\nfindings by category:")
    print(
        tabulate(
            [[c, n] for c, n in result.by_category.items()],
            headers=["category", "count"],
            tablefmt="github",
        )
    )

    report = evaluate(result.findings, base_manifest)
    print("\nGROUND-TRUTH SCORING (against the planted defect manifest)")
    print(
        tabulate(
            [
                [cat, f"{hit}/{total}", f"{hit / total:.0%}"]
                for cat, (hit, total) in report.category_recall.items()
            ],
            headers=["category", "found", "recall"],
            tablefmt="github",
        )
    )
    print(report.summary())
    if report.missed:
        print("missed:", ", ".join(f"{p.file}:{p.line} {p.rule}" for p in report.missed))
    print(f"additional (unplanted) findings: {report.extra_findings}")

    md_path, json_path = write_reports(
        result, out_dir, "review", title="Demo repo review"
    )

    diff_result, _ = review_diff(
        base_root, head_root, planner=args.planner, config=config
    )
    _print_result(diff_result, planner, "DIFF-AWARE REVIEW (base -> head)")
    introduced = {p.key for p in head_manifest.plants if p.introduced}
    reported = {f.key for f in diff_result.findings}
    caught = len(introduced & reported)
    preexisting = [p for p in head_manifest.plants if not p.introduced]
    suppressed = sum(1 for p in preexisting if p.key not in reported)
    print(
        f"defects introduced by the change: {len(introduced)}; "
        f"reported on changed lines: {caught}; "
        f"pre-existing defects correctly suppressed: {suppressed}/{len(preexisting)}"
    )
    diff_md, diff_json = write_reports(
        diff_result, out_dir, "diff_review", title="Diff-aware review"
    )

    trace_path = os.path.join(out_dir, "agent_trace.txt")
    with open(trace_path, "w", encoding="utf-8") as handle:
        handle.write(result.trace)
    with open(os.path.join(out_dir, "evaluation.json"), "w", encoding="utf-8") as handle:
        json.dump(report.to_dict(), handle, indent=2)

    print(f"\ndemo finished in {time.perf_counter() - started:.1f}s")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    target = os.path.abspath(args.path)
    if not os.path.exists(target):
        print(f"no such path: {target}")
        return 2
    files = None
    root = target
    if os.path.isfile(target):
        root = os.path.dirname(target)
        files = [os.path.basename(target)]
    result, planner = review_repo(
        root, planner=args.planner, config=_config(args), files=files
    )
    _print_result(result, planner, f"REVIEW {target}")
    out_dir = args.out or default_output_dir()
    md_path, json_path = write_reports(result, out_dir, args.stem)
    print(f"\nreports: {md_path}\n         {json_path}")
    if args.fail_under is not None and result.health.score < args.fail_under:
        print(f"FAIL: health {result.health.score:.1f} < --fail-under {args.fail_under}")
        return 1
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    if not args.base or not args.head:
        print("provide --base and --head directories")
        return 2
    result, planner = review_diff(
        os.path.abspath(args.base),
        os.path.abspath(args.head),
        planner=args.planner,
        config=_config(args),
        scope=args.scope,
        context=args.context,
    )
    _print_result(result, planner, "DIFF-AWARE REVIEW")
    out_dir = args.out or default_output_dir()
    md_path, json_path = write_reports(
        result, out_dir, args.stem, title="Diff-aware review"
    )
    print(f"\nreports: {md_path}\n         {json_path}")
    blocking = [f for f in result.findings if f.severity in ("critical", "high")]
    if args.block_on_severity and blocking:
        print(f"FAIL: {len(blocking)} critical/high finding(s) introduced by this change")
        return 1
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    result, _ = review_repo(
        os.path.abspath(args.path), planner="rules", config=_config(args)
    )
    fns = sorted(
        (fn for m in result.metrics.values() for fn in m.functions),
        key=lambda f: (-f.complexity, f.file, f.line),
    )[: args.top]
    print(
        tabulate(
            [
                [
                    fn.name,
                    f"{fn.file}:{fn.line}",
                    fn.complexity,
                    fn.nesting,
                    fn.length,
                    fn.params,
                    "yes" if fn.has_docstring else "no",
                ]
                for fn in fns
            ],
            headers=["function", "location", "cc", "nesting", "lines", "params", "docstring"],
            tablefmt="github",
        )
    )
    print(f"\nhealth score: {result.health.score:.1f}/100 (grade {result.health.grade})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m reviewer",
        description="Autonomous multi-pass Python code review agent with forward-chaining rules",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="generate planted defect repo, review and score")
    demo.add_argument("--seed", type=int, default=42)
    _add_threshold_flags(demo)
    demo.set_defaults(func=cmd_demo)

    review = sub.add_parser("review", help="review repository or file")
    review.add_argument("path")
    review.add_argument("--out", default=None)
    review.add_argument("--stem", default="review")
    review.add_argument("--fail-under", type=float, default=None)
    _add_threshold_flags(review)
    review.set_defaults(func=cmd_review)

    diff = sub.add_parser("diff", help="review changed lines")
    diff.add_argument("--base", required=True)
    diff.add_argument("--head", required=True)
    diff.add_argument("--scope", choices=("line", "function"), default="line")
    diff.add_argument("--context", type=int, default=0)
    diff.add_argument("--out", default=None)
    diff.add_argument("--stem", default="diff_review")
    diff.add_argument("--block-on-severity", action="store_true")
    _add_threshold_flags(diff)
    diff.set_defaults(func=cmd_diff)

    metrics = sub.add_parser("metrics", help="complexity & coupling tables")
    metrics.add_argument("path")
    metrics.add_argument("--top", type=int, default=15)
    _add_threshold_flags(metrics)
    metrics.set_defaults(func=cmd_metrics)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
