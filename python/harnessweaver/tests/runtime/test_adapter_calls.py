"""Model and tool calls an adapter makes through its own client and tools (ADR-0037)."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.errors import RunEscalated

from .conftest import Builder, scripted, spec

pytestmark = pytest.mark.anyio

OWN_CALLS = {"runner": {"use": "session", "handler": "hw_testkit_tools:own_calls"}}


@pytest.fixture
async def app(build: Builder, tmp_path: Path) -> AsyncIterator[hw.Harness]:
    state = {"use": "sqlite", "path": str(tmp_path / "state.db"), "record": True}
    harness = build(spec(models=scripted({"text": "unused"}), tasks={"t": OWN_CALLS}, state=state))
    yield harness
    await harness.aclose()


async def test_own_calls_are_governed(app: hw.Harness, testkit: Any) -> None:
    result = await app.run("t", "Oslo")
    assert result.ok, result.error
    assert result.output == {"text": "sunny", "weather": {"sky": "clear"}}
    assert testkit.RECORDER.handled == [("weather", {"city": "Oslo"})]
    assert testkit.RECORDER.requests == []  # the spec's model wasn't asked
    hooks = [e.hook for e in result.trace if e.kind is hw.TraceKind.HOOK and e.hook is not None]
    assert [h for h in hooks if h.startswith(("model.", "tool."))] == [
        "model.before",
        "model.after",
        "tool.before",
        "tool.after",
    ]
    (allowed,) = [e for e in result.trace if e.source == "harness.governor"]
    assert allowed.details["decision"] == "allow"


async def test_a_replay_never_uses_them(app: hw.Harness, testkit: Any) -> None:
    result = await app.run("t", "Oslo")
    report = await app.replay(result.run_id)
    assert not report.differs
    assert (report.model_answers_used, report.missing_tool_results) == (1, 0)
    assert len(testkit.RECORDER.handled) == 1  # the replay ran no tool
    assert testkit.RECORDER.notes == [("own model", 1)]  # nor asked the adapter's model


async def test_their_tools_follow_the_spec(build: Builder, testkit: Any) -> None:
    rules = [{"id": "no-weather", "when": "true", "effect": "deny"}]
    models = scripted({"text": "unused"})
    app = build(spec(models=models, tasks={"t": OWN_CALLS}, policy={"rules": rules}))
    result = await app.run("t", "Oslo")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "policy_denied"
    assert testkit.RECORDER.handled == []


async def test_their_own_approvals_wait_for_a_human(build: Builder, testkit: Any) -> None:
    handler = {"runner": {"use": "session", "handler": "hw_testkit_tools:own_approval"}}
    app = build(spec(models=scripted({"text": "unused"}), tasks={"t": handler}))
    waiting = await app.run("t", "Oslo")
    assert waiting.status is hw.RunStatus.AWAITING_APPROVAL
    assert waiting.approval is not None
    assert (waiting.approval.reason, waiting.approval.approver_role) == (
        "the framework asks first",
        "ops",
    )
    assert waiting.approval.call is not None
    assert waiting.approval.call.name == "weather"
    assert testkit.RECORDER.handled == []
    ops = hw.Principal(id="olga", roles=("ops",))
    done = await app.approve(waiting.run_id, waiting.approval.approval_id, approver=ops)
    assert done.output == {"sky": "clear"}
    assert testkit.RECORDER.handled == [("weather", {"city": "Oslo"})]
    async with app.session() as s:
        call = hw.ToolCall(id="call_w", name="weather", arguments={})
        assert isinstance(s.run_context.approval_needed(call, "asks"), RunEscalated)
