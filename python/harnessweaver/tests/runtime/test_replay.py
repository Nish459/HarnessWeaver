"""Recording runs and replaying them against the current spec (ADR-0035)."""

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.state import RecordedCall, call_digest
from harnessweaver.errors import NotFound, ProviderError, SpecError
from harnessweaver.harness.replay import RecordedTools

from .conftest import Builder, spec
from .governance_support import FINANCE, call, refund_tool, tool_spec

pytestmark = pytest.mark.anyio

type Opener = Callable[[dict[str, Any]], hw.Harness]


@pytest.fixture
async def opened(build: Builder) -> AsyncIterator[Opener]:
    """Build harnesses whose SQLite stores are closed after the test."""
    harnesses: list[hw.Harness] = []

    def open_(document: dict[str, Any]) -> hw.Harness:
        harnesses.append(build(document, tools=None))
        return harnesses[-1]

    yield open_
    for harness in harnesses:
        await harness.aclose()


def recorded(tmp_path: Path, *replies: dict[str, Any], **sections: Any) -> dict[str, Any]:
    refund_tool(tmp_path, approval={"when": "args.amount_usd > 100", "approver_role": "finance"})
    state = {"use": "sqlite", "path": str(tmp_path / "state.db"), "record": True}
    return tool_spec(*replies, tools=["refund_payment"], state=state, **sections)


async def kinds(app: hw.Harness, run_id: str) -> list[str]:
    return [c.kind for c in await app._state.recording(run_id)]  # pyright: ignore[reportPrivateUsage]


async def test_a_recorded_run_replays_the_same(
    opened: Opener, tmp_path: Path, testkit: Any
) -> None:
    app = opened(recorded(tmp_path, call("refund_payment", amount_usd=5)))
    result = await app.run("t", "refund my order")
    assert result.ok, result.error
    assert await kinds(app, result.run_id) == ["model", "tool", "model"]
    report = await app.replay(result.run_id)
    assert (report.same_status, report.same_output, report.changes) == (True, True, ())
    assert (report.model_answers, report.model_answers_used, report.changed_requests) == (2, 2, 0)
    assert report.missing_tool_results == 0
    assert not report.differs
    assert len(testkit.RECORDER.handled) == 1  # the replay ran no tool
    with pytest.raises(NotFound):
        await app.result(report.replayed.run_id)  # the replay's run stayed in memory


async def test_a_stricter_spec_changes_the_replay(
    opened: Opener, tmp_path: Path, testkit: Any
) -> None:
    app = opened(recorded(tmp_path, call("refund_payment", amount_usd=5)))
    result = await app.run("t", "refund my order")
    rules = [{"id": "no-refunds", "when": "args.amount_usd > 1", "effect": "deny"}]
    stricter = opened(recorded(tmp_path, {"text": "x"}, policy={"rules": rules}))
    report = await stricter.replay(result.run_id)
    assert report.differs
    assert (report.original.status, report.replayed.status) == ("completed", "blocked")
    assert report.model_answers_used == 1  # the run stopped before asking again
    added = [(c.source, c.code) for c in report.changes if c.change == "added"]
    assert ("harness.governor", "policy_denied") in added


async def test_recorded_approvals_answer_the_replay(
    opened: Opener, tmp_path: Path, testkit: Any
) -> None:
    app = opened(recorded(tmp_path, call("refund_payment", amount_usd=500)))
    waiting = await app.run("t", "refund my order")
    assert waiting.approval is not None
    done = await app.approve(waiting.run_id, waiting.approval.approval_id, approver=FINANCE)
    assert done.ok, done.error
    assert await kinds(app, done.run_id) == ["model", "approval", "tool", "model"]
    report = await app.replay(done.run_id)
    assert report.replayed.status is hw.RunStatus.COMPLETED
    assert not report.differs
    assert report.changes == ()


async def test_changed_requests_are_counted(opened: Opener, tmp_path: Path, testkit: Any) -> None:
    app = opened(recorded(tmp_path, {"text": "done"}))
    result = await app.run("t", "Mail alice@example.com")
    guards = {"input": [{"id": "pii", "use": "pii.regex"}]}
    redacting = opened(recorded(tmp_path, {"text": "x"}, guardrails=guards))
    report = await redacting.replay(result.run_id)
    assert not report.differs  # same status, same output
    assert report.changed_requests == 1  # the model was asked something else
    assert ("harness.guard", "guard_fired") in [(c.source, c.code) for c in report.changes]


async def test_what_cant_be_replayed(opened: Opener, tmp_path: Path, testkit: Any) -> None:
    models = {"provider": "scripted", "replies": [{"text": "done"}]}
    app = opened(spec(models=models, tasks={"t": {"runner": "direct"}}))
    result = await app.run("t", "hello")
    with pytest.raises(SpecError, match=r"has no recording; set state\.record: true"):
        await app.replay(result.run_id)
    with pytest.raises(NotFound, match="no run"):
        await app.replay("run_missing")
    async with app.session() as s:
        await s.generate(prompt=None, messages=[hw.Message.user("hi")])
    assert s.result is not None
    with pytest.raises(SpecError, match="didn't run a task"):
        await app.replay(s.result.run_id)


async def test_recorded_tools_never_execute(testkit: Any) -> None:
    result = hw.ToolResult(call_id="call_1", output={"ok": True})
    calls = [
        hw.ToolCall(id="call_1", name="refund_payment", arguments={"amount_usd": 5}),
    ]
    recording = [
        RecordedCall(run_id="r", seq=0, kind="tool", digest=call_digest(calls[0]), result=result)
    ]
    tools = RecordedTools(None, recording)
    env = hw.Envelope.new(tenant="t", principal="p")
    again = calls[0].model_copy(update={"id": "call_9"})
    assert (await tools.execute(again, env)).call_id == "call_9"
    with pytest.raises(ProviderError, match="no result for this call to refund_payment"):
        await tools.execute(again, env)  # each recorded result answers once
    assert tools.missing == 1
    assert tools.describe("refund_payment") is None
