"""Suspend, approve, edit, reject, expire, cancel and resume (DESIGNS No. 18)."""

from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.registry import PluginCatalog
from harnessweaver.core.state import Grant
from harnessweaver.core.trace import TraceKind
from harnessweaver.errors import NotFound, PolicyDenied, ValidationFailed

from .conftest import Builder, scripted, spec, write

pytestmark = pytest.mark.anyio

REFUND = {"id": "c1", "name": "refund", "arguments": {"amount": 500}}
FINANCE = hw.Principal(id="bob", roles=("finance",))


def refund_spec(**extra: Any) -> dict[str, Any]:
    document = spec(
        models=scripted({"tool_calls": [REFUND]}, after_tool={"text": "refunded"}),
        middleware=[
            {"use": "testkit.audit"},
            {
                "use": "testkit.script",
                "rules": [
                    {
                        "hook": "tool.before",
                        "outcome": "suspend",
                        "tool": "refund",
                        "reason": "refunds need finance",
                        "approver_role": "finance",
                    }
                ],
            },
        ],
        tasks={"refund": {"runner": "direct", "tools": ["refund"]}},
    )
    document.update(extra)
    return document


async def suspended(harness: hw.Harness) -> hw.RunResult:
    result = await harness.run("refund", "refund order 7", principal="alice")
    assert result.status is hw.RunStatus.AWAITING_APPROVAL
    assert result.approval is not None
    return result


async def test_a_suspended_call_waits_for_approval(build: Builder, testkit: Any) -> None:
    harness = build(refund_spec())
    result = await suspended(harness)
    approval = result.approval
    assert approval is not None
    assert approval.reason == "refunds need finance"
    assert approval.approver_role == "finance"
    assert approval.call is not None
    assert approval.call.arguments == {"amount": 500}
    assert approval.tool is not None
    assert approval.tool.name == "refund"
    assert approval.expires_at is not None  # approvals.timeout from the defaults profile
    assert testkit.RECORDER.tool_calls == []
    assert result.ended_at is None
    assert (await harness.result(result.run_id)).status is hw.RunStatus.AWAITING_APPROVAL


async def test_approving_resumes_where_the_run_stopped(build: Builder, testkit: Any) -> None:
    harness = build(refund_spec())
    first = await suspended(harness)
    assert first.approval is not None
    result = await harness.approve(first.run_id, first.approval.approval_id, approver=FINANCE)
    assert result.ok
    assert result.output == "refunded"
    assert [c.arguments for c in testkit.RECORDER.tool_calls] == [{"amount": 500}]
    assert len(testkit.RECORDER.requests) == 2  # no repeated first model call
    hooks = [e.hook.value for e in result.trace if e.kind is TraceKind.HOOK and e.hook]
    assert hooks.count("approval.resolved") == 1
    assert hooks.count("tool.before") == 2
    assert [e.seq for e in result.trace] == list(range(len(result.trace)))


async def test_the_approver_needs_the_role(build: Builder) -> None:
    harness = build(refund_spec())
    first = await suspended(harness)
    assert first.approval is not None
    with pytest.raises(PolicyDenied):
        await harness.approve(first.run_id, first.approval.approval_id, approver="mallory")
    with pytest.raises(NotFound):
        await harness.approve(first.run_id, "apr_wrong", approver=FINANCE)
    with pytest.raises(NotFound):
        await harness.approve("run_missing", first.approval.approval_id, approver=FINANCE)


async def test_rejecting_blocks_the_run(build: Builder, testkit: Any) -> None:
    harness = build(refund_spec())
    first = await suspended(harness)
    assert first.approval is not None
    result = await harness.approve(
        first.run_id, first.approval.approval_id, "reject", approver=FINANCE, reason="no"
    )
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "approval_rejected"
    assert testkit.RECORDER.tool_calls == []


async def test_editing_runs_the_edited_arguments(build: Builder, testkit: Any) -> None:
    harness = build(refund_spec())
    first = await suspended(harness)
    assert first.approval is not None
    with pytest.raises(ValidationFailed):
        await harness.approve(first.run_id, first.approval.approval_id, "edit", approver=FINANCE)
    result = await harness.approve(
        first.run_id,
        first.approval.approval_id,
        "edit",
        approver=FINANCE,
        edited_args={"amount": 50},
    )
    assert result.ok
    assert [c.arguments for c in testkit.RECORDER.tool_calls] == [{"amount": 50}]


@pytest.mark.parametrize(
    ("on_timeout", "status"), [("escalate", "escalated"), ("reject", "blocked")]
)
async def test_an_expired_request_ends_the_run(
    build: Builder, testkit: Any, on_timeout: str, status: str
) -> None:
    clock = hw.FakeClock()
    harness = build(refund_spec(approvals={"timeout": "1h", "on_timeout": on_timeout}), clock=clock)
    first = await suspended(harness)
    assert first.approval is not None
    clock.advance("2h")
    result = await harness.approve(first.run_id, first.approval.approval_id, approver=FINANCE)
    assert result.status == status
    assert result.error is not None
    assert result.error.details["code"] == "approval_timeout"
    assert testkit.RECORDER.tool_calls == []


async def test_cancelling_a_waiting_run(build: Builder) -> None:
    harness = build(refund_spec())
    first = await suspended(harness)
    result = await harness.cancel(first.run_id)
    assert result.status is hw.RunStatus.CANCELLED
    assert (await harness.cancel(first.run_id)) == result
    with pytest.raises(NotFound):
        await harness.cancel("run_missing")
    assert first.approval is not None
    with pytest.raises(NotFound):
        await harness.approve(first.run_id, first.approval.approval_id, approver=FINANCE)


async def test_resume_after_a_crash(build: Builder, testkit: Any) -> None:
    harness = build(refund_spec())
    first = await suspended(harness)
    assert first.approval is not None
    with pytest.raises(NotFound, match="still waiting"):
        await harness.resume(first.run_id)
    # Simulate approve() persisting the answer and the process dying before the run ended.
    state = harness._state
    checkpoint = await state.get_checkpoint(first.run_id)
    assert checkpoint is not None
    assert checkpoint.approval_hook == "tool.before"
    assert checkpoint.approval_digest is not None
    decision = hw.ApprovalDecision(
        approval_id=first.approval.approval_id, decision="approve", approver=FINANCE
    )
    grant = Grant(hook="tool.before", digest=checkpoint.approval_digest, decision=decision)
    await state.put_checkpoint(checkpoint.model_copy(update={"approval": None, "grants": (grant,)}))
    record = await state.get_run(first.run_id)
    assert record is not None
    await state.put_run(record.model_copy(update={"status": hw.RunStatus.RUNNING}))
    result = await harness.resume(first.run_id)
    assert result.ok
    with pytest.raises(NotFound):
        await harness.resume(first.run_id)


async def test_an_output_approval_resumes_with_the_same_output(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "final answer"}),
            middleware=[
                {
                    "use": "testkit.script",
                    "rules": [{"hook": "output.before", "outcome": "suspend"}],
                }
            ],
            tasks={"t": {"runner": "direct"}},
        )
    )
    first = await harness.run("t", "q")
    assert first.status is hw.RunStatus.AWAITING_APPROVAL
    assert first.approval is not None
    assert first.approval.call is None
    with pytest.raises(ValidationFailed):
        await harness.approve(
            first.run_id, first.approval.approval_id, "edit", approver="x", edited_args={}
        )
    result = await harness.approve(first.run_id, first.approval.approval_id, approver="x")
    assert result.ok
    assert result.output == "final answer"


async def test_a_session_runner_reruns_its_handler(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[
                {
                    "use": "testkit.script",
                    "rules": [{"hook": "tool.before", "outcome": "suspend", "tool": "refund"}],
                }
            ],
            tasks={"flow": {"runner": {"use": "session", "handler": "hw_testkit:refund_flow"}}},
        )
    )
    first = await harness.run("flow", {"amount": 9})
    assert first.status is hw.RunStatus.AWAITING_APPROVAL
    assert first.approval is not None
    result = await harness.approve(first.run_id, first.approval.approval_id, approver="x")
    assert result.ok
    assert result.output == {"done": {"refunded": 9}}
    assert [n for n in testkit.RECORDER.notes if n[0] == "refund_flow"] == [
        ("refund_flow", {"amount": 9}),
        ("refund_flow", {"amount": 9}),
    ]
    assert len(testkit.RECORDER.tool_calls) == 1


async def test_a_run_resumes_in_another_process(tmp_path: Path, testkit: Any) -> None:
    db = tmp_path / "state.db"
    document = refund_spec(state={"use": "sqlite", "path": str(db)})
    path = write(tmp_path, document)

    def load() -> hw.Harness:
        return hw.Harness.load(path, tools=testkit.FakeTools(), catalog=PluginCatalog())

    async with load() as first_process:
        first = await first_process.run("refund", "refund order 7")
    assert first.approval is not None
    async with load() as second_process:
        result = await second_process.approve(
            first.run_id, first.approval.approval_id, approver=FINANCE
        )
        assert result.ok
        assert result.output == "refunded"
        assert (await second_process.result(first.run_id)).ok


async def test_every_hook_point_fires(build: Builder, testkit: Any) -> None:
    """A run through all 13 hook points: 12 in a run that completes, plus run.error."""
    harness = build(
        spec(
            models=scripted({"text": "x", "chunks": ["Hel", "lo"]}),
            middleware=[
                {"use": "testkit.audit"},
                {
                    "use": "testkit.script",
                    "rules": [{"hook": "tool.before", "outcome": "suspend", "tool": "refund"}],
                },
            ],
            tasks={
                "tour": {"runner": {"use": "session", "handler": "hw_testkit:full_tour"}},
                "broken": {
                    "runner": {
                        "use": "workflow",
                        "steps": [{"id": "x", "handler": "hw_testkit:explode"}],
                    }
                },
            },
        )
    )
    first = await harness.run("tour", {"amount": 3})
    assert first.approval is not None
    done = await harness.approve(first.run_id, first.approval.approval_id, approver="x")
    assert done.ok
    assert done.output == {"route": None, "refund": {"refunded": 3}, "text": "Hello"}
    failed = await harness.run("broken", None)
    assert failed.status is hw.RunStatus.FAILED
    fired = {e.hook for r in (done, failed) for e in r.trace if e.kind is TraceKind.HOOK}
    assert fired == set(hw.HookPoint)
    assert set(testkit.RECORDER.hooks) == {h.value for h in hw.HookPoint}
