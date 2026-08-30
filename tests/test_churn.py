"""Change-proneness: where the numbers come from and which source wins.

The git path is exercised against a real throwaway repository rather than a
mocked `subprocess.run`, because the bug this file exists to pin was about what
git actually prints: `git log --numstat` reports paths relative to the repository
root, not to `-C`, so reviewing a subdirectory matched nothing.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from reviewer.churn import (
    ChurnModel,
    build_churn,
    diff_churn,
    git_churn,
    repo_prefix,
    static_churn,
)
from reviewer.metrics import module_metrics

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="git is not on PATH")

GIT = shutil.which("git") or "git"
IDENTITY = ["-c", "user.name=test", "-c", "user.email=test@example.invalid"]


def _run(*args: str, cwd) -> None:
    subprocess.run([GIT, *IDENTITY, *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    """A repository with a package in a subdirectory and two commits touching it."""
    _run("init", "-q", cwd=tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "hot.py").write_text("x = 1\n", encoding="utf-8")
    (pkg / "cold.py").write_text("y = 1\n", encoding="utf-8")
    _run("add", "-A", cwd=tmp_path)
    _run("commit", "-qm", "first", cwd=tmp_path)
    (pkg / "hot.py").write_text("x = 1\nz = 2\nw = 3\n", encoding="utf-8")
    _run("add", "-A", cwd=tmp_path)
    _run("commit", "-qm", "second", cwd=tmp_path)
    return tmp_path


def test_prefix_is_empty_at_the_repository_root(repo):
    assert repo_prefix(GIT, str(repo)) == ""


def test_prefix_names_the_subdirectory(repo):
    assert repo_prefix(GIT, str(repo / "pkg")) == "pkg/"


def test_prefix_of_a_non_repository_is_empty(tmp_path):
    assert repo_prefix(GIT, str(tmp_path)) == ""


def test_churn_at_the_root_is_keyed_on_repo_paths(repo):
    assert set(git_churn(str(repo))) == {"pkg/hot.py", "pkg/cold.py"}


def test_churn_in_a_subdirectory_is_keyed_the_way_the_review_is(repo):
    """Regression: these used to come back prefixed and match nothing."""
    assert set(git_churn(str(repo / "pkg"))) == {"hot.py", "cold.py"}


def test_the_edited_file_has_more_churn(repo):
    churn = git_churn(str(repo / "pkg"))
    assert churn["hot.py"] > churn["cold.py"]


def test_a_directory_with_no_history_has_no_churn(tmp_path):
    assert git_churn(str(tmp_path)) == {}


# -- the model on top of the numbers ----------------------------------------
def test_normalized_scales_against_the_busiest_file():
    model = ChurnModel({"a.py": 10.0, "b.py": 5.0}, "git-log")
    assert model.normalized("a.py") == 1.0
    assert model.normalized("b.py") == 0.5
    assert model.normalized("missing.py") == 0.0


def test_normalized_is_zero_when_nothing_churned():
    assert ChurnModel({}, "static-proxy").normalized("a.py") == 0.0


def test_diff_churn_counts_changed_lines():
    assert diff_churn({"a.py": {1, 2, 3}}) == {"a.py": 3.0}


def test_static_churn_grows_with_size_and_branchiness():
    small = module_metrics("s.py", "x = 1\n")
    big = module_metrics("b.py", "def f(a):\n    if a:\n        return 1\n    return 2\n")
    scores = static_churn({"s.py": small, "b.py": big})
    assert scores["b.py"] > scores["s.py"]


def test_a_diff_wins_over_git_history(repo):
    model = build_churn(str(repo), {}, {"pkg/hot.py": {1, 2}})
    assert model.source == "diff"


def test_git_wins_over_the_static_proxy(repo):
    metrics = {rel: module_metrics(rel, "x = 1\n") for rel in ("hot.py", "cold.py")}
    assert build_churn(str(repo / "pkg"), metrics).source == "git-log"


def test_the_static_proxy_is_the_last_resort(tmp_path):
    metrics = {"a.py": module_metrics("a.py", "x = 1\n")}
    assert build_churn(str(tmp_path), metrics).source == "static-proxy"
