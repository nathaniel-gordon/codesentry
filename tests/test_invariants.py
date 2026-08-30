"""Invariants that must hold for every input, checked over generated ones.

There is no hypothesis in this environment, so the generators here are a seeded
`random.Random` over a grammar of source-line fragments. The seed is fixed so a
failure is reproducible, and the cases are printed by pytest on failure because
they are ordinary arguments.

What these buy over the example-based tests: the example tests check that
specific inputs produce specific findings, and these check the properties the
whole pipeline must preserve whatever the input is - scores stay in range,
counts add up, the ranking is really sorted, analysis is deterministic and does
not mutate the tree it reads.
"""
from __future__ import annotations

import hashlib
import json
import random

import pytest

from reviewer.analyzers import (
    CATEGORIES,
    RULES,
    SEVERITY_ORDER,
    AnalyzerConfig,
    Finding,
    analyze_source,
)
from reviewer.cache import AnalysisCache
from reviewer.diffing import iter_python_files
from reviewer.errors import InputError
from reviewer.metrics import module_metrics
from reviewer.pipeline import review_repo
from reviewer.review import ReviewSession
from reviewer.suppression import Suppressions

SEED = 20240817

#: Fragments a generated function body is assembled from. Some are defects,
#: some are benign; the mix is the point - the invariants must hold either way.
FRAGMENTS = (
    "    total = 0",
    "    for i in range(len(items)):",
    "        total += items[i]",
    "    if total > 10:",
    "        total = eval('1 + 1')",
    "    try:",
    "        total += 1",
    "    except Exception:",
    "        pass",
    "    handle = open('x.txt')",
    "    query = 'SELECT * FROM t WHERE id = ' + str(total)",
    "    password = 'hunter2hunter2hunter2'",
    "    assert total is not None",
    "    while total > 100:",
    "        total -= 1",
    "    return total",
)


def _program(rng: random.Random, lines: int = 12) -> str:
    """Build a syntactically plausible module out of the fragment grammar."""
    body = [rng.choice(FRAGMENTS) for _ in range(lines)]
    body.append("    return None")
    return "def generated(items):\n" + "\n".join(body) + "\n"


def _programs(count: int = 25, seed: int = SEED) -> list[str]:
    rng = random.Random(seed)
    return [_program(rng) for _ in range(count)]


PROGRAMS = _programs()


def _random_findings(rng: random.Random, count: int) -> list[Finding]:
    severities = list(SEVERITY_ORDER)
    rules = sorted(RULES)
    return [
        Finding(file=f"f{rng.randrange(4)}.py", line=rng.randrange(1, 50),
                rule=rng.choice(rules), severity=rng.choice(severities),
                message="m", suggestion="s", category=rng.choice(CATEGORIES))
        for _ in range(count)
    ]


# -- analysis ---------------------------------------------------------------
@pytest.mark.parametrize("source", PROGRAMS)
def test_every_finding_is_in_vocabulary(source):
    for finding in analyze_source("g.py", source, AnalyzerConfig()):
        assert finding.severity in SEVERITY_ORDER
        assert finding.category in CATEGORIES
        assert finding.rule in RULES
        assert finding.line >= 1


@pytest.mark.parametrize("source", PROGRAMS)
def test_findings_land_inside_the_file(source):
    limit = len(source.splitlines())
    for finding in analyze_source("g.py", source, AnalyzerConfig()):
        assert 1 <= finding.line <= limit


@pytest.mark.parametrize("source", PROGRAMS)
def test_analysis_is_deterministic(source):
    first = [f.to_dict() for f in analyze_source("g.py", source, AnalyzerConfig())]
    second = [f.to_dict() for f in analyze_source("g.py", source, AnalyzerConfig())]
    assert first == second


@pytest.mark.parametrize("source", PROGRAMS[:8])
def test_analysis_never_writes_to_the_tree(source, tmp_path):
    path = tmp_path / "g.py"
    path.write_text(source, encoding="utf-8")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    review_repo(str(tmp_path), config=AnalyzerConfig())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("source", PROGRAMS[:8])
def test_metrics_agree_with_the_functions_they_describe(source):
    module = module_metrics("g.py", source)
    for fn in module.functions:
        assert fn.end_line >= fn.line
        assert fn.length == fn.end_line - fn.line + 1
        assert fn.complexity >= 1
        # the risk model asks for the complexity around a line; a line inside a
        # function must never score below that function.
        assert module.complexity_at(fn.line) >= fn.complexity


# -- scoring ----------------------------------------------------------------
@pytest.mark.parametrize("count", [0, 1, 5, 40, 200])
def test_health_stays_inside_the_scale(count, tmp_path):
    rng = random.Random(SEED + count)
    (tmp_path / "g.py").write_text(_program(rng), encoding="utf-8")
    session = ReviewSession(str(tmp_path))
    session.analyze_all()
    score = session.health(_random_findings(rng, count))
    assert 0.0 <= score.score <= 100.0
    assert score.grade in {"A", "B", "C", "D", "F"}


@pytest.mark.parametrize("source", PROGRAMS[:10])
def test_the_result_is_internally_consistent(source, tmp_path):
    (tmp_path / "g.py").write_text(source, encoding="utf-8")
    result, _engine = review_repo(str(tmp_path), config=AnalyzerConfig())
    assert sum(result.by_severity.values()) == len(result.findings)
    assert sum(result.by_category.values()) == len(result.findings)
    assert sum(n for _f, _r, n in result.file_risk()) == len(result.findings)
    assert result.total_sloc >= 0


@pytest.mark.parametrize("source", PROGRAMS[:10])
def test_findings_come_back_ranked(source, tmp_path):
    (tmp_path / "g.py").write_text(source, encoding="utf-8")
    result, _engine = review_repo(str(tmp_path), config=AnalyzerConfig())
    risks = [f.risk for f in result.findings]
    assert risks == sorted(risks, reverse=True)
    assert result.top_risks(3) == result.findings[:3]


@pytest.mark.parametrize("source", PROGRAMS[:10])
def test_the_payload_survives_json(source, tmp_path):
    (tmp_path / "g.py").write_text(source, encoding="utf-8")
    result, _engine = review_repo(str(tmp_path), config=AnalyzerConfig())
    assert json.loads(json.dumps(result.to_dict()))["summary"]["findings"] == \
        len(result.findings)


# -- the cache is a pure round trip -----------------------------------------
@pytest.mark.parametrize("source", PROGRAMS[:10])
def test_a_cached_run_equals_an_uncached_one(source, tmp_path):
    (tmp_path / "g.py").write_text(source, encoding="utf-8")
    cold, _ = review_repo(str(tmp_path), config=AnalyzerConfig())
    with AnalysisCache(str(tmp_path / "c.db"), AnalyzerConfig()) as cache:
        seeded, _ = review_repo(str(tmp_path), config=AnalyzerConfig(), cache=cache)
        warm, _ = review_repo(str(tmp_path), config=AnalyzerConfig(), cache=cache)
    assert [f.to_dict() for f in warm.findings] == [f.to_dict() for f in cold.findings]
    assert warm.cache_stats["hits"] == 1 and seeded.cache_stats["misses"] == 1


# -- suppression ------------------------------------------------------------
@pytest.mark.parametrize("count", [0, 3, 25])
def test_suppression_is_idempotent(count):
    rng = random.Random(SEED + count)
    findings = _random_findings(rng, count)
    once = Suppressions().apply(list(findings))
    twice = Suppressions().apply(list(once))
    assert [f.key for f in once] == [f.key for f in twice]


# -- path handling ----------------------------------------------------------
@pytest.mark.parametrize("suffix", [
    "a.py", "pkg/b.py", "./c.py", "pkg/../d.py", "pkg/sub/e.py",
])
def test_contained_paths_resolve_under_the_root(suffix, tmp_path):
    session = ReviewSession(str(tmp_path))
    assert session.abspath(suffix).startswith(str(tmp_path))


@pytest.mark.parametrize("escape", [
    "../x.py", "../../x.py", "pkg/../../x.py", "a/b/../../../x.py",
])
def test_escaping_paths_are_always_refused(escape, tmp_path):
    session = ReviewSession(str(tmp_path))
    with pytest.raises(InputError):
        session.abspath(escape)


def test_discovered_paths_are_relative_and_posix(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "top.py").write_text("y = 2\n", encoding="utf-8")
    found = iter_python_files(str(tmp_path))
    assert found == ["pkg/m.py", "top.py"]
    for rel in found:
        assert "\\" not in rel and not rel.startswith("/")
