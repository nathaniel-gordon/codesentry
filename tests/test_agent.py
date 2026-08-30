"""The optional agent path, which must agree with the direct one.

`--mode agent` is a demonstration now rather than the mandatory execution path,
so the property worth pinning is that routing the same repository through the
plan/act/observe loop produces the same findings - and that a tool failure comes
back as a recorded error instead of a swallowed observation.
"""
from __future__ import annotations

import pytest

from reviewer.agent import AgentTools, build_agent
from reviewer.errors import ToolInputError
from reviewer.pipeline import review_repo
from reviewer.review import ReviewSession

SOURCE = ('"""Module."""\n\n\ndef run(text):\n    """Run."""\n'
          '    return eval(text)\n')


@pytest.fixture
def project(tmp_path):
    (tmp_path / "m.py").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "settings.ini").write_text(
        "[db]\npassword = hunter2hunter2hunter2\n", encoding="utf-8")
    return tmp_path


def test_agent_mode_finds_what_direct_mode_finds(project):
    direct, direct_engine = review_repo(str(project), mode="direct")
    agent, agent_engine = review_repo(str(project), mode="agent", planner="rules")
    assert direct_engine == "direct"
    assert agent_engine.startswith("agent:")
    assert {f.key for f in direct.findings} == {f.key for f in agent.findings}


def test_agent_mode_reads_the_config_file_secret(project):
    result, _ = review_repo(str(project), mode="agent", planner="rules")
    assert any(f.file.endswith("settings.ini") for f in result.findings)


def test_agent_run_records_no_errors(project):
    session = ReviewSession(str(project))
    agent, _used = build_agent(session, planner="rules")
    agent.run("review the repository")
    assert agent.errors == []
    assert session.errors == []


def test_out_of_scope_path_is_a_typed_tool_error(project):
    tools = AgentTools(ReviewSession(str(project)))
    with pytest.raises(ToolInputError):
        tools.analyze_file("../outside.py")


def test_bad_regex_is_a_typed_tool_error(project):
    tools = AgentTools(ReviewSession(str(project)))
    with pytest.raises(ToolInputError):
        tools.search_pattern("(unclosed")


def test_loop_records_a_tool_failure_instead_of_hiding_it(project):
    """The old loop caught bare Exception, so a crash became trace prose."""
    session = ReviewSession(str(project))
    agent, _used = build_agent(session, planner="rules")

    def explode(**_kwargs):
        raise ToolInputError("simulated tool failure")

    agent.registry.get("analyze_file").handler = explode
    agent.run("review the repository")
    assert agent.errors, "a failing tool must be recorded, not swallowed"


def test_analyzer_failure_reaches_the_session_in_agent_mode(project, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("simulated analyzer bug")

    monkeypatch.setattr("reviewer.review.analyze_source", explode)
    result, _ = review_repo(str(project), mode="agent", planner="rules")
    assert result.ok is False
    assert result.errors
