"""Change-proneness ("churn") signals used to rank findings.

Risk is not severity alone: a critical bug in a file nobody touches is less
urgent than the same bug in the file three people edit every week, because the
churned file will keep re-breaking. Three churn sources are supported, in order
of fidelity:

1. `git_churn`   - real added+deleted line counts from `git log --numstat`.
2. `diff_churn`  - changed-line counts from the baseline/head comparison the
                   diff-aware review already computed.
3. `static_churn` - an offline structural proxy, used when neither VCS history
                   nor a baseline exists. Documented, not invented: size,
                   number of entry points and branchiness are the file-level
                   predictors of future edits available from source alone.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from .metrics import ModuleMetrics


@dataclass
class ChurnModel:
    """Per-file churn values plus the provenance of the numbers."""

    raw: dict[str, float]
    source: str

    @property
    def peak(self) -> float:
        """Largest raw churn value (used to normalise)."""
        return max(self.raw.values(), default=0.0)

    def normalized(self, file: str) -> float:
        """Churn of `file` scaled to 0..1 against the busiest file in the repo."""
        peak = self.peak
        if peak <= 0:
            return 0.0
        return min(1.0, self.raw.get(file, 0.0) / peak)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable view."""
        return {"source": self.source,
                "raw": {k: round(v, 2) for k, v in sorted(self.raw.items())}}


#: git config keys that name a program git will run. The reviewed repository is
#: untrusted and git reads its .git/config, so all three are pinned on the
#: command line where the repository's own config cannot win.
_PINS = ("-c", "core.fsmonitor=false", "-c", "core.pager=cat",
         "-c", "core.hooksPath=/dev/null")


def repo_prefix(git: str, root: str, timeout: float = 10.0) -> str:
    """Where `root` sits inside its repository, as a trailing-slash prefix.

    `git log --numstat` prints paths relative to the repository root, not to
    `-C`. Reviewing a subdirectory therefore produced churn keyed on
    `pkg/mod.py` while the review keys on `mod.py`, nothing matched, and the
    model silently fell back to the static proxy. Returns "" at the top of a
    repository, or when the question cannot be answered.
    """
    cmd = [git, *_PINS, "-C", root, "rev-parse", "--show-prefix"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip().replace("\\", "/")


def git_churn(root: str, max_commits: int = 400, timeout: float = 20.0) -> dict[str, float]:
    """Added+deleted lines per file from git history; {} when unavailable.

    Runs without a shell and tolerates every failure mode (no git binary, not a
    repository, shallow clone) because the reviewer must work offline.
    """
    git = shutil.which("git")
    if git is None:
        return {}
    cmd = [git, *_PINS, "-C", root, "log",
           f"-n{max_commits}", "--numstat", "--pretty=format:", "--no-renames"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return {}
    if proc.returncode != 0:
        return {}
    churn: dict[str, float] = {}
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        if not path.endswith(".py"):
            continue
        try:
            total = int(added) + int(deleted)
        except ValueError:
            continue  # binary files report '-'
        churn[path.replace("\\", "/")] = churn.get(path.replace("\\", "/"), 0.0) + total
    prefix = repo_prefix(git, root)
    if prefix:
        churn = {p[len(prefix):]: v for p, v in churn.items() if p.startswith(prefix)}
    return churn


def diff_churn(changed_lines: dict[str, set[int]]) -> dict[str, float]:
    """Churn = number of changed lines per file in the reviewed diff."""
    return {file: float(len(lines)) for file, lines in changed_lines.items()}


def static_churn(metrics: dict[str, ModuleMetrics]) -> dict[str, float]:
    """Structural volatility proxy: size + entry points + branchiness.

    Weights are deliberately simple and documented rather than fitted: one point
    per source line, ten per function (each is an edit surface) and five per unit
    of peak complexity (branchy code attracts fixes).
    """
    return {
        path: float(m.sloc + 10 * len(m.functions) + 5 * m.max_complexity)
        for path, m in metrics.items()
    }


def build_churn(root: str, metrics: dict[str, ModuleMetrics],
                changed_lines: dict[str, set[int]] | None = None) -> ChurnModel:
    """Pick the highest-fidelity churn source available for this review."""
    if changed_lines:
        return ChurnModel(diff_churn(changed_lines), "diff")
    from_git = git_churn(root)
    if from_git:
        scoped = {p: v for p, v in from_git.items() if p in metrics}
        if scoped:
            return ChurnModel(scoped, "git-log")
    return ChurnModel(static_churn(metrics), "static-proxy")
