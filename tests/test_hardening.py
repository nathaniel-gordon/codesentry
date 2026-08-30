"""Input validation on the surfaces that take untrusted values.

Under `--mode agent --planner llm` the tool arguments are model-generated, and a
unified diff's file headers are whatever the patch author typed. Both used to be
trusted: an out-of-vocabulary severity passed `record()` and then raised
KeyError inside the risk model, after the agent loop's handler, killing the run.
"""
from __future__ import annotations

import pytest

from reviewer.errors import InputError, ToolInputError
from reviewer.review import ReviewSession
from reviewer.textscan import MAX_PATTERN_LEN, iter_text_files, safe_compile, search_text_files


@pytest.fixture
def session(tmp_path):
    (tmp_path / "m.py").write_text('"""M."""\n', encoding="utf-8")
    return ReviewSession(str(tmp_path))


# -- path containment ------------------------------------------------------
def test_parent_traversal_is_rejected(session):
    with pytest.raises(InputError):
        session.abspath("../../secrets.txt")


def test_absolute_path_is_rejected(session):
    with pytest.raises(InputError):
        session.abspath("/etc/passwd")


def test_windows_drive_path_is_rejected(session):
    with pytest.raises(InputError):
        session.abspath("C:/Windows/win.ini")


def test_relative_path_inside_the_root_is_allowed(session):
    assert session.abspath("m.py").endswith("m.py")


def test_recording_outside_the_root_is_rejected(session):
    with pytest.raises(InputError):
        session.record("../evil.py", 1, "eval-exec", "m", "s")


# -- record() vocabulary ---------------------------------------------------
def test_unknown_severity_is_rejected_not_crashed_on(session):
    with pytest.raises(ToolInputError):
        session.record("m.py", 1, "custom", "m", "s", severity="warning")


def test_unknown_category_is_rejected(session):
    with pytest.raises(ToolInputError):
        session.record("m.py", 1, "custom", "m", "s", severity="high",
                       category="stylistic")


def test_non_numeric_line_is_rejected(session):
    with pytest.raises(ToolInputError):
        session.record("m.py", "abc", "eval-exec", "m", "s")


def test_empty_rule_is_rejected(session):
    with pytest.raises(ToolInputError):
        session.record("m.py", 1, "   ", "m", "s")


def test_a_valid_record_survives_scoring(session):
    assert session.record("m.py", 1, "eval-exec", "m", "s")
    result = session.finalize()
    assert result.health.score <= 100.0  # would KeyError on a bad severity
    assert result.by_severity["critical"] == 1


# -- bounded text search ---------------------------------------------------
def test_nested_quantifier_is_refused():
    with pytest.raises(ToolInputError):
        safe_compile(r"(a+)+$")


def test_overlong_pattern_is_refused():
    with pytest.raises(ToolInputError):
        safe_compile("a" * (MAX_PATTERN_LEN + 1))


def test_invalid_regex_is_a_typed_error():
    with pytest.raises(ToolInputError):
        safe_compile("(unclosed")


def test_empty_pattern_is_refused():
    with pytest.raises(ToolInputError):
        safe_compile("")


def test_only_text_extensions_are_opened(tmp_path):
    (tmp_path / "settings.ini").write_text("token = abcdefghijkl\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01token = abcdefghijkl")
    (tmp_path / "notes.md").write_text("token = abcdefghijkl\n", encoding="utf-8")
    listed = iter_text_files(str(tmp_path))
    assert listed == ["settings.ini"]


def test_hits_are_capped(tmp_path):
    (tmp_path / "big.ini").write_text("token = abcdefghijkl\n" * 100, encoding="utf-8")
    hits = search_text_files(str(tmp_path), r"token", max_hits=5)
    assert len(hits) == 5


def test_oversized_files_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr("reviewer.textscan.MAX_FILE_BYTES", 10)
    (tmp_path / "big.ini").write_text("token = abcdefghijkl\n" * 10, encoding="utf-8")
    assert search_text_files(str(tmp_path), r"token") == []


# -- diff input ------------------------------------------------------------
def test_patch_paths_cannot_escape_the_root(tmp_path):
    from reviewer.pipeline import review_patch
    (tmp_path / "m.py").write_text('"""M."""\n', encoding="utf-8")
    patch = tmp_path / "p.diff"
    patch.write_text("--- a/../../etc/shadow\n+++ b/../../etc/shadow\n"
                     "@@ -0,0 +1,1 @@\n+import os\n", encoding="utf-8")
    result, _ = review_patch(str(tmp_path), str(patch))
    assert all(".." not in f.file for f in result.findings)
    assert result.ok


def test_missing_patch_file_is_a_typed_error(tmp_path):
    from reviewer.pipeline import review_patch
    with pytest.raises(InputError):
        review_patch(str(tmp_path), str(tmp_path / "absent.diff"))
