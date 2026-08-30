"""codesentry command line.

Subcommands, roughly in order of how often they get used:

    review   <path...>         analyze files or directories
    diff     --base --head     analyze only the lines two snapshots differ on
    patch    <root> --diff     the same, driven by a unified diff file
    metrics  <path>            complexity and coupling tables
    rules                      the rule table and the packs it groups into
    baseline <path...>         freeze today's findings so only new ones fail
    cache                      inspect or clear the incremental cache
    demo                       generate the planted-defect corpus and review it
    eval                       score detection and precision against that corpus

Exit codes are a contract, not decoration (see `errors`): 0 clean, 1 a gate
failed, 2 the invocation or configuration was wrong, 3 the tool itself failed -
which includes any file that could not be analyzed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from .analyzers import PACKS, RULES, SEVERITY_ORDER, AnalyzerConfig
from .cache import AnalysisCache, clear_cache, default_cache_path
from .config import Settings, apply_overrides, load_settings
from .datagen import write_demo_pair
from .diffing import iter_python_files
from .errors import (EXIT_GATE_FAILED, EXIT_INTERNAL, EXIT_OK, CodeSentryError,
                     InputError, UsageError)
from .evaluation import evaluate, rule_scores
from .logging_setup import configure_logging, current_run_id, get_logger
from .pipeline import default_output_dir, review_diff, review_patch, review_repo
from .report import write_reports
from .review import ReviewResult
from .sarif import write_sarif
from .suppression import Baseline, Suppressions
from .tables import text_table

log = get_logger("cli")

FORMATS = ("md", "json", "sarif")
THRESHOLD_FLAGS = ("max_complexity", "max_nesting", "max_fn_lines", "max_params",
                   "max_line_len", "max_imports")


# --------------------------------------------------------------------------
# argument plumbing
# --------------------------------------------------------------------------
def _add_threshold_flags(parser: argparse.ArgumentParser) -> None:
    """Threshold overrides. Default None means 'not given', so config wins."""
    group = parser.add_argument_group("thresholds (override [tool.codesentry])")
    group.add_argument("--max-complexity", type=int, default=None)
    group.add_argument("--max-nesting", type=int, default=None)
    group.add_argument("--max-fn-lines", type=int, default=None)
    group.add_argument("--max-params", type=int, default=None)
    group.add_argument("--max-line-len", type=int, default=None)
    group.add_argument("--max-imports", type=int, default=None)


def _add_rule_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("rule selection")
    group.add_argument("--pack", action="append", default=None, metavar="NAME",
                       help=f"enable one pack, repeatable ({', '.join(sorted(PACKS))})")
    group.add_argument("--select", action="append", default=[], metavar="RULE",
                       help="run only these rules, repeatable")
    group.add_argument("--ignore", action="append", default=[], metavar="RULE",
                       help="disable a rule, repeatable")
    group.add_argument("--no-config", action="store_true",
                       help="ignore [tool.codesentry] in pyproject.toml")


def _add_engine_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("engine")
    group.add_argument("--mode", choices=("direct", "agent"), default="direct",
                       help="'agent' runs the plan/act/observe loop over the same tools")
    group.add_argument("--planner", choices=("auto", "rules", "llm"), default="auto",
                       help="agent mode only; 'llm' needs ANTHROPIC_API_KEY")
    group.add_argument("--no-cache", dest="cache", action="store_false", default=None,
                       help="re-analyze every file instead of reusing cached results")
    group.add_argument("--cache-path", default=None, help="override the cache database")
    group.add_argument("--clear-cache", action="store_true",
                       help="delete the cache before running")


def _add_output_flags(parser: argparse.ArgumentParser, stem: str) -> None:
    group = parser.add_argument_group("output")
    group.add_argument("--format", action="append", default=None, choices=FORMATS,
                       metavar="FMT", help=f"repeatable: {', '.join(FORMATS)}")
    group.add_argument("--stdout", action="store_true",
                       help="write the report to stdout instead of to files")
    group.add_argument("--out", default=None, help="report directory")
    group.add_argument("--stem", default=stem, help="report filename stem")
    group.add_argument("--quiet", action="store_true",
                       help="suppress the summary tables; gates still apply")


def _add_gate_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("gates and suppression")
    group.add_argument("--fail-on-severity", choices=tuple(SEVERITY_ORDER), default=None,
                       help="exit 1 when a finding at or above this severity remains")
    group.add_argument("--fail-under", type=float, default=None,
                       help="exit 1 when the health score is below this value")
    group.add_argument("--baseline", default=None,
                       help="ignore findings listed in this baseline file")


def _add_log_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--log-level", default="warning",
                        choices=("debug", "info", "warning", "error"))
    parser.add_argument("--log-format", default="text", choices=("text", "json"))


def _settings(args: argparse.Namespace, root: str) -> Settings:
    """File config plus command-line overrides, validated."""
    settings = load_settings(root, use_config=not getattr(args, "no_config", False))
    thresholds = {name: getattr(args, name, None) for name in THRESHOLD_FLAGS}
    return apply_overrides(
        settings, thresholds=thresholds,
        packs=tuple(args.pack) if getattr(args, "pack", None) else None,
        select=tuple(getattr(args, "select", ()) or ()),
        ignore=tuple(getattr(args, "ignore", ()) or ()),
        fail_under=getattr(args, "fail_under", None),
        fail_on_severity=getattr(args, "fail_on_severity", None),
        baseline=getattr(args, "baseline", None),
        cache=getattr(args, "cache", None))


def resolve_targets(paths: list[str], exclude: tuple[str, ...] = ()
                    ) -> tuple[str, list[str] | None]:
    """Turn N files and directories into one review root plus a file list.

    pre-commit appends every staged filename to the hook command, so accepting
    exactly one path (which is what the CLI used to do) made any commit touching
    two Python files fail with an argparse usage error.
    """
    resolved = [os.path.abspath(p) for p in paths]
    for path in resolved:
        if not os.path.exists(path):
            raise InputError("no such path", path=path)
    dirs = [p for p in resolved if os.path.isdir(p)]
    files = [p for p in resolved if not os.path.isdir(p)]
    if len(resolved) == 1 and dirs:
        root = dirs[0]
        selected = None
    else:
        anchors = dirs + [os.path.dirname(p) for p in files]
        try:
            root = os.path.commonpath(anchors) if anchors else os.getcwd()
        except ValueError as exc:  # different drives on Windows
            raise UsageError("paths must share a drive to be reviewed together",
                             paths=len(resolved)) from exc
        if os.path.isfile(root):  # commonpath of one file is that file
            root = os.path.dirname(root)
        rels = {os.path.relpath(p, root).replace(os.sep, "/") for p in files
                if p.endswith(".py")}
        for directory in dirs:
            prefix = os.path.relpath(directory, root).replace(os.sep, "/")
            rels.update(f"{prefix}/{rel}" if prefix != "." else rel
                        for rel in iter_python_files(directory))
        selected = sorted(rels)
        if not selected:
            raise InputError("no Python files among the given paths",
                             paths=len(resolved))
    if exclude:
        pool = selected if selected is not None else iter_python_files(root)
        kept = [rel for rel in pool
                if not any(rel == pat or rel.startswith(pat.rstrip("/") + "/")
                           for pat in exclude)]
        selected = kept
    return root, selected


def _open_cache(args: argparse.Namespace, root: str,
                settings: Settings) -> AnalysisCache | None:
    """Open (or clear) the incremental cache, unless it is switched off."""
    path = args.cache_path or default_cache_path(root)
    if getattr(args, "clear_cache", False):
        cleared = clear_cache(path)
        log.info("cache cleared", extra={"path": path, "existed": cleared})
    if not settings.cache:
        return None
    return AnalysisCache(path, settings.analyzer)


def _suppressions(settings: Settings) -> Suppressions:
    baseline = Baseline.load(settings.baseline) if settings.baseline else None
    return Suppressions(baseline=baseline)


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
def _print_result(result: ReviewResult, engine: str, label: str) -> None:
    print(f"\n{label}")
    print("-" * len(label))
    cache = result.cache_stats
    print(f"engine={engine}  files={len(result.metrics)}  sloc={result.total_sloc}  "
          f"churn={result.churn.source}  findings={len(result.findings)}  "
          f"cache={cache.get('hits', 0)}h/{cache.get('misses', 0)}m")
    print(f"health score: {result.health.score:.1f}/100 (grade {result.health.grade})")
    print(text_table(["severity", "count"],
                     [[sev, result.by_severity[sev]] for sev in SEVERITY_ORDER]))
    suppressed = result.suppressed
    if suppressed.get("by_pragma") or suppressed.get("by_baseline"):
        print(f"suppressed: {suppressed.get('by_pragma', 0)} by pragma, "
              f"{suppressed.get('by_baseline', 0)} by baseline")
    if result.findings:
        print("\ntop risks (severity x complexity x churn):")
        print(text_table(["risk", "severity", "location", "rule", "message"],
                         [[f"{f.risk:.1f}", f.severity, f.location(), f.rule,
                           f.message[:64]] for f in result.top_risks(8)]))


def _print_errors(result: ReviewResult) -> None:
    """Analyzer failures are printed loudly; they are why the run exits 3."""
    if not result.errors:
        return
    print(f"\n{len(result.errors)} file(s) could not be analyzed:", file=sys.stderr)
    for error in result.errors[:20]:
        print(f"  {error.file}: {error.message}", file=sys.stderr)


def _emit(result: ReviewResult, args: argparse.Namespace, title: str) -> list[str]:
    """Write (or print) the requested formats; returns the paths written."""
    formats = tuple(dict.fromkeys(args.format or ("md", "json")))
    if args.stdout and args.quiet and result.ok and not result.findings:
        # A pre-commit hook should print nothing when it passes. --quiet with
        # --stdout means "only speak when there is something to say".
        return []
    if args.stdout:
        from .report import render_markdown
        from .sarif import render_sarif
        for fmt in formats:
            if fmt == "md":
                sys.stdout.write(render_markdown(result, title=title))
            elif fmt == "json":
                json.dump(result.to_dict(), sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                json.dump(render_sarif(result), sys.stdout, indent=2)
                sys.stdout.write("\n")
        return []
    out_dir = args.out or default_output_dir()
    written: list[str] = []
    if "md" in formats or "json" in formats:
        md_path, json_path = write_reports(result, out_dir, args.stem, title=title)
        written += [p for p, fmt in ((md_path, "md"), (json_path, "json"))
                    if fmt in formats]
    if "sarif" in formats:
        written.append(write_sarif(result, os.path.join(out_dir,
                                                        f"{args.stem}.sarif")))
    return written


def _gate(result: ReviewResult, settings: Settings) -> int:
    """Apply the exit-code contract to a finished review."""
    if not result.ok:
        return EXIT_INTERNAL
    if settings.fail_on_severity:
        floor = SEVERITY_ORDER[settings.fail_on_severity]
        blocking = [f for f in result.findings if SEVERITY_ORDER[f.severity] <= floor]
        if blocking:
            print(f"FAIL: {len(blocking)} finding(s) at or above "
                  f"{settings.fail_on_severity}", file=sys.stderr)
            return EXIT_GATE_FAILED
    if settings.fail_under is not None and result.health.score < settings.fail_under:
        print(f"FAIL: health {result.health.score:.1f} < --fail-under "
              f"{settings.fail_under}", file=sys.stderr)
        return EXIT_GATE_FAILED
    return EXIT_OK


def _finish(result: ReviewResult, engine: str, args: argparse.Namespace,
            settings: Settings, label: str, title: str) -> int:
    if not args.quiet and not args.stdout:
        _print_result(result, engine, label)
    written = _emit(result, args, title)
    if written and not args.quiet:
        print("\nreports: " + "\n         ".join(written))
    _print_errors(result)
    return _gate(result, settings)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_review(args: argparse.Namespace) -> int:
    """Analyze the given files and directories."""
    settings = _settings(args, args.paths[0])
    root, files = resolve_targets(args.paths, settings.exclude)
    cache = _open_cache(args, root, settings)
    try:
        result, engine = review_repo(root, mode=args.mode, planner=args.planner,
                                     config=settings.analyzer, files=files,
                                     cache=cache,
                                     suppressions=_suppressions(settings))
    finally:
        if cache is not None:
            cache.close()
    return _finish(result, engine, args, settings, f"REVIEW {root}", "Code review")


def cmd_diff(args: argparse.Namespace) -> int:
    """Analyze only the lines that differ between two directory snapshots."""
    settings = _settings(args, args.head)
    cache = _open_cache(args, os.path.abspath(args.head), settings)
    try:
        result, engine = review_diff(os.path.abspath(args.base),
                                     os.path.abspath(args.head), mode=args.mode,
                                     planner=args.planner, config=settings.analyzer,
                                     scope=args.scope, context=args.context,
                                     cache=cache,
                                     suppressions=_suppressions(settings))
    finally:
        if cache is not None:
            cache.close()
    return _finish(result, engine, args, settings, "DIFF-AWARE REVIEW",
                   "Diff-aware review")


def cmd_patch(args: argparse.Namespace) -> int:
    """Analyze a working tree restricted to the lines a unified diff touches."""
    settings = _settings(args, args.path)
    root = os.path.abspath(args.path)
    cache = _open_cache(args, root, settings)
    try:
        result, engine = review_patch(root, args.diff, mode=args.mode,
                                      planner=args.planner, config=settings.analyzer,
                                      scope=args.scope, context=args.context,
                                      cache=cache,
                                      suppressions=_suppressions(settings))
    finally:
        if cache is not None:
            cache.close()
    return _finish(result, engine, args, settings, f"PATCH REVIEW {root}",
                   "Patch review")


def cmd_metrics(args: argparse.Namespace) -> int:
    """Print the complexity table for one tree."""
    settings = _settings(args, args.path)
    root, files = resolve_targets([args.path], settings.exclude)
    result, _ = review_repo(root, config=settings.analyzer, files=files)
    fns = sorted((fn for m in result.metrics.values() for fn in m.functions),
                 key=lambda f: (-f.complexity, f.file, f.line))[:args.top]
    print(text_table(["function", "location", "cc", "nesting", "lines", "params",
                      "docstring"],
                     [[fn.name, f"{fn.file}:{fn.line}", fn.complexity, fn.nesting,
                       fn.length, fn.params, "yes" if fn.has_docstring else "no"]
                      for fn in fns]))
    print(f"\nhealth score: {result.health.score:.1f}/100 "
          f"(grade {result.health.grade})")
    _print_errors(result)
    return EXIT_INTERNAL if not result.ok else EXIT_OK


def cmd_rules(args: argparse.Namespace) -> int:
    """List every rule, its pack, its severity and what it is for."""
    if args.json:
        json.dump({"packs": {p: sorted(r) for p, r in PACKS.items()},
                   "rules": {rid: {"severity": s.severity, "category": s.category,
                                   "why": s.why} for rid, s in sorted(RULES.items())}},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
        return EXIT_OK
    rows = [[rid, spec.category, spec.severity, spec.why.split(";")[0][:72]]
            for rid, spec in sorted(RULES.items(),
                                    key=lambda kv: (kv[1].category, kv[0]))]
    print(text_table(["rule", "pack", "severity", "why"], rows))
    print(f"\n{len(RULES)} rules in {len(PACKS)} packs: "
          + ", ".join(f"{p} ({len(r)})" for p, r in sorted(PACKS.items())))
    return EXIT_OK


def cmd_baseline(args: argparse.Namespace) -> int:
    """Freeze the findings that exist today so only new ones fail the build."""
    settings = _settings(args, args.paths[0])
    root, files = resolve_targets(args.paths, settings.exclude)
    result, _ = review_repo(root, config=settings.analyzer, files=files)
    if not result.ok:
        _print_errors(result)
        print("refusing to write a baseline from an incomplete run", file=sys.stderr)
        return EXIT_INTERNAL
    path = Baseline.from_findings(result.findings).write(args.output)
    print(f"baseline: {path} ({len(result.findings)} finding(s) frozen)")
    return EXIT_OK


def cmd_cache(args: argparse.Namespace) -> int:
    """Show or clear the incremental analysis cache."""
    root = os.path.abspath(args.path)
    path = args.cache_path or default_cache_path(root)
    if args.clear:
        print(f"cleared: {path}" if clear_cache(path) else f"nothing to clear: {path}")
        return EXIT_OK
    with AnalysisCache(path, AnalyzerConfig()) as cache:
        summary = cache.summary()
    if args.prune:
        with AnalysisCache(path, AnalyzerConfig()) as cache:
            print(f"pruned {cache.prune(args.prune)} row(s)")
    print(text_table(["key", "value"], sorted(summary.items())))
    return EXIT_OK


def cmd_demo(args: argparse.Namespace) -> int:
    """Generate the planted-defect corpus, review it, and score the result."""
    started = time.perf_counter()
    out_dir = args.out or default_output_dir()
    demo_dir = os.path.join(out_dir, "demo_repo")
    shutil.rmtree(demo_dir, ignore_errors=True)
    base_manifest, head_manifest = write_demo_pair(demo_dir)
    base_root = os.path.join(demo_dir, "base")
    head_root = os.path.join(demo_dir, "head")
    print("=" * 74)
    print("codesentry demo - planted-defect corpus")
    print("=" * 74)
    print(f"generated: {base_root}")
    print(f"  {len(base_manifest.files)} files, {len(base_manifest.plants)} planted "
          f"defects, {len(base_manifest.clean_files)} files written to be clean")

    config = AnalyzerConfig()
    result, engine = review_repo(base_root, mode=args.mode, planner=args.planner,
                                 config=config)
    _print_result(result, engine, "FULL REVIEW")
    report = evaluate(result.findings, base_manifest)
    print("\nscored against the planted-defect manifest:")
    print(text_table(["category", "found", "recall"],
                     [[cat, f"{hit}/{total}", f"{hit / total:.0%}"]
                      for cat, (hit, total) in report.category_recall.items()]))
    print(report.summary())
    if report.missed:
        print("missed: " + ", ".join(f"{p.file}:{p.line} {p.rule}"
                                     for p in report.missed))
    write_reports(result, out_dir, "review", title="Demo repo review")
    write_sarif(result, os.path.join(out_dir, "review.sarif"))

    diff_result, _ = review_diff(base_root, head_root, mode=args.mode,
                                 planner=args.planner, config=config)
    _print_result(diff_result, engine, "DIFF-AWARE REVIEW (base -> head)")
    introduced = {p.key for p in head_manifest.plants if p.introduced}
    reported = {f.key for f in diff_result.findings}
    # Only plants inside the files the diff actually touched test suppression.
    # Counting the whole corpus would credit the tool for staying silent about
    # files it never opened.
    touched = set(diff_result.metrics)
    in_scope = [p for p in head_manifest.plants
                if not p.introduced and p.file in touched]
    print(f"defects introduced by the change: {len(introduced)}; "
          f"reported on changed lines: {len(introduced & reported)}; "
          f"pre-existing defects in the changed files, not re-reported: "
          f"{sum(1 for p in in_scope if p.key not in reported)}/{len(in_scope)}")
    write_reports(diff_result, out_dir, "diff_review", title="Diff-aware review")
    with open(os.path.join(out_dir, "evaluation.json"), "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2)
    _print_errors(result)
    print(f"\ndemo finished in {time.perf_counter() - started:.1f}s")
    return EXIT_INTERNAL if not (result.ok and diff_result.ok) else EXIT_OK


def cmd_eval(args: argparse.Namespace) -> int:
    """Measure per-rule precision and recall against the corpus."""
    out_dir = args.out or default_output_dir()
    corpus = os.path.join(out_dir, "eval_corpus")
    shutil.rmtree(corpus, ignore_errors=True)
    manifest, _ = write_demo_pair(corpus)
    result, _ = review_repo(os.path.join(corpus, "base"), config=AnalyzerConfig())
    if not result.ok:
        _print_errors(result)
        return EXIT_INTERNAL
    report = evaluate(result.findings, manifest)
    scores = rule_scores(result.findings, manifest)
    rows = [[s.rule, s.tp, s.fp, s.fn, f"{s.precision:.2f}", f"{s.recall:.2f}",
             f"{s.f1:.2f}"] for s in scores]
    print(text_table(["rule", "tp", "fp", "fn", "precision", "recall", "f1"], rows))
    tp = sum(s.tp for s in scores)
    fp = sum(s.fp for s in scores)
    fn = sum(s.fn for s in scores)
    print(f"\ntotals: tp={tp} fp={fp} fn={fn}  "
          f"precision={tp / (tp + fp) if tp + fp else 0:.2f}  "
          f"recall={tp / (tp + fn) if tp + fn else 0:.2f}")
    print(f"corpus: {len(manifest.files)} files, {len(manifest.plants)} planted "
          f"defects, {len(manifest.clean_files)} benign files "
          f"(false positives are counted on those only)")
    payload = report.to_dict()
    payload["per_rule"] = [s.to_dict() for s in scores]
    path = os.path.join(out_dir, "evaluation.json")
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    print(f"wrote {os.path.abspath(path)}")
    return EXIT_OK


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Build the full argument parser."""
    parser = argparse.ArgumentParser(
        prog="codesentry",
        description="AST-based Python static analyzer with SARIF output, "
                    "an incremental cache and a planted-defect corpus.",
        epilog="exit codes: 0 clean, 1 gate failed, 2 usage, 3 internal failure")
    _add_log_flags(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="analyze files or directories")
    review.add_argument("paths", nargs="+")
    for add in (_add_threshold_flags, _add_rule_flags, _add_engine_flags,
                _add_gate_flags):
        add(review)
    _add_output_flags(review, "review")
    review.set_defaults(func=cmd_review)

    diff = sub.add_parser("diff", help="analyze only changed lines")
    diff.add_argument("--base", required=True)
    diff.add_argument("--head", required=True)
    diff.add_argument("--scope", choices=("line", "function"), default="line")
    diff.add_argument("--context", type=int, default=0)
    for add in (_add_threshold_flags, _add_rule_flags, _add_engine_flags,
                _add_gate_flags):
        add(diff)
    _add_output_flags(diff, "diff_review")
    diff.set_defaults(func=cmd_diff)

    patch = sub.add_parser("patch", help="analyze the lines a unified diff touches")
    patch.add_argument("path")
    patch.add_argument("--diff", required=True, help="unified diff file")
    patch.add_argument("--scope", choices=("line", "function"), default="line")
    patch.add_argument("--context", type=int, default=0)
    for add in (_add_threshold_flags, _add_rule_flags, _add_engine_flags,
                _add_gate_flags):
        add(patch)
    _add_output_flags(patch, "patch_review")
    patch.set_defaults(func=cmd_patch)

    metrics = sub.add_parser("metrics", help="complexity and coupling tables")
    metrics.add_argument("path")
    metrics.add_argument("--top", type=int, default=15)
    _add_threshold_flags(metrics)
    _add_rule_flags(metrics)
    metrics.set_defaults(func=cmd_metrics)

    rules = sub.add_parser("rules", help="list the rule table and its packs")
    rules.add_argument("--json", action="store_true")
    rules.set_defaults(func=cmd_rules)

    baseline = sub.add_parser("baseline", help="freeze today's findings")
    baseline.add_argument("paths", nargs="+")
    baseline.add_argument("--output", default="codesentry-baseline.json")
    _add_threshold_flags(baseline)
    _add_rule_flags(baseline)
    baseline.set_defaults(func=cmd_baseline)

    cache = sub.add_parser("cache", help="inspect or clear the analysis cache")
    cache.add_argument("path", nargs="?", default=".")
    cache.add_argument("--cache-path", default=None)
    cache.add_argument("--clear", action="store_true")
    cache.add_argument("--prune", type=int, default=0, metavar="KEEP",
                       help="keep at most KEEP entries per file")
    cache.set_defaults(func=cmd_cache)

    demo = sub.add_parser("demo", help="generate the corpus, review it and score")
    demo.add_argument("--out", default=None)
    _add_engine_flags(demo)
    demo.set_defaults(func=cmd_demo)

    evaluate_cmd = sub.add_parser("eval", help="per-rule precision and recall")
    evaluate_cmd.add_argument("--out", default=None)
    evaluate_cmd.set_defaults(func=cmd_eval)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the command, and map failures onto exit codes."""
    args = build_parser().parse_args(argv)
    run_id = configure_logging(args.log_level, args.log_format)
    try:
        return args.func(args)
    except CodeSentryError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        log.error("run failed", extra={"code": exc.code})
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("interrupted", file=sys.stderr)
        return EXIT_INTERNAL
    finally:
        log.info("run complete", extra={"run_id": run_id or current_run_id()})


if __name__ == "__main__":
    sys.exit(main())
