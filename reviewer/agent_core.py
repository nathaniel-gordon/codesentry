"""Agent core: tool registry + plan/act/observe loop with a full trace.

Drives either the deterministic policy in `agent.py` or a live Claude planner.

The loop treats *expected* tool failures - a typed `CodeSentryError` such as a
bad regex or a file that will not parse - as observations, because a planner
should be able to see them and try something else. Everything else propagates.
Catching bare `Exception` here is what previously turned an analyzer crash into
a line of trace text and let the run exit 0 reporting no findings.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .errors import CodeSentryError


@dataclass
class Tool:
    """One callable the planner can invoke, with its parameter documentation."""

    name: str
    description: str
    handler: Callable[..., Any]
    params: dict[str, str] = field(default_factory=dict)  # name -> description

    def spec(self) -> str:
        """One catalog line: name, parameters and description."""
        ps = ", ".join(f"{k}: {v}" for k, v in self.params.items()) or "no parameters"
        return f"- {self.name}({ps}): {self.description}"


class ToolRegistry:
    """Name -> Tool lookup, plus the catalog block a planner prompt needs."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add a tool, replacing any tool already registered under its name."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Look a tool up by name, or None when it is not registered."""
        return self._tools.get(name)

    def catalog(self) -> str:
        """Every registered tool as one prompt-ready block."""
        return "\n".join(t.spec() for t in self._tools.values())


@dataclass
class Step:
    """One plan/act/observe cycle, kept for the trace."""

    n: int
    thought: str
    action: str
    action_input: dict
    observation: str
    elapsed_ms: float


class Agent:
    """Plan/act/observe loop.

    policy(goal, history, registry) -> dict with keys:
        thought: str, action: tool name or 'finish', action_input: dict
    Projects provide a deterministic policy; an LLM policy can wrap ClaudeLLM.
    """

    def __init__(self, name: str, registry: ToolRegistry,
                 policy: Callable[[str, list[Step], ToolRegistry], dict],
                 max_steps: int = 12):
        self.name = name
        self.registry = registry
        self.policy = policy
        self.max_steps = max_steps
        self.trace: list[Step] = []
        self.errors: list[str] = []

    def run(self, goal: str) -> str:
        """Drive the policy until it finishes or runs out of steps."""
        self.trace = []
        self.errors = []
        for n in range(1, self.max_steps + 1):
            decision = self.policy(goal, self.trace, self.registry)
            action = decision.get("action", "finish")
            action_input = decision.get("action_input", {}) or {}
            thought = decision.get("thought", "")
            if action == "finish":
                final = str(action_input.get("answer", thought or "done"))
                self.trace.append(Step(n, thought, "finish", action_input, final, 0.0))
                return final
            tool = self.registry.get(action)
            t0 = time.perf_counter()
            if tool is None:
                obs = f"ERROR: unknown tool '{action}'"
                self.errors.append(obs)
            else:
                try:
                    obs = str(tool.handler(**action_input))
                except CodeSentryError as exc:
                    # A typed failure the planner is allowed to react to. It is
                    # still an error: recorded here and, for analyzer failures,
                    # on the session, so the run cannot exit 0.
                    obs = f"ERROR: {exc.code}: {exc}"
                    self.errors.append(obs)
                except TypeError as exc:
                    # Wrong argument names from a planner, not a tool bug.
                    obs = f"ERROR: bad tool arguments: {exc}"
                    self.errors.append(obs)
            self.trace.append(Step(n, thought, action, action_input,
                                   obs, (time.perf_counter() - t0) * 1000))
        return "max steps reached without finish"

    def trace_report(self) -> str:
        """Render the run as readable text for the report and the trace file."""
        lines = [f"=== Agent trace: {self.name} ({len(self.trace)} steps) ==="]
        for s in self.trace:
            lines.append(f"[{s.n}] {s.action} {json.dumps(s.action_input, default=str)[:120]}")
            if s.thought:
                lines.append(f"    thought: {s.thought[:200]}")
            lines.append(f"    -> {s.observation[:300]}")
        return "\n".join(lines)


def llm_policy_factory(llm, system_prompt: str, parse_retries: int = 2):
    """Build an LLM-backed policy: the model returns JSON {thought, action, action_input}."""

    def policy(goal: str, history: list[Step], registry: ToolRegistry) -> dict:
        hist = "\n".join(
            f"step {s.n}: called {s.action}({json.dumps(s.action_input, default=str)}) "
            f"-> {s.observation[:400]}" for s in history) or "(no steps yet)"
        prompt = (
            f"GOAL: {goal}\n\nTOOLS:\n{registry.catalog()}\n\nHISTORY:\n{hist}\n\n"
            'Reply with ONLY a JSON object: {"thought": "...", "action": "<tool or finish>", '
            '"action_input": {...}}. Use action "finish" with action_input {"answer": "..."} '
            "when the goal is complete.")
        for _ in range(parse_retries + 1):
            raw = llm.complete(prompt, system=system_prompt)
            try:
                start, end = raw.index("{"), raw.rindex("}") + 1
                return json.loads(raw[start:end])
            except (ValueError, json.JSONDecodeError):
                continue
        return {"thought": "planner output unparseable", "action": "finish",
                "action_input": {"answer": "planning failed"}}

    return policy
