"""Background runs: submit, stream, cancel."""

from typing import Any

import anyio
import anyio.lowlevel
import pytest

import harnessweaver as hw
from harnessweaver.errors import NotFound, SpecError

from .conftest import Builder, scripted, spec

pytestmark = pytest.mark.anyio


async def test_submit_needs_an_open_harness(build: Builder) -> None:
    harness = build(spec(models=scripted({"text": "x"}), tasks={"t": {"runner": "direct"}}))
    with pytest.raises(SpecError, match="async with"):
        await harness.submit("t", "q")


async def test_submit_then_stream_to_the_end(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[{"use": "testkit.audit"}],
            tasks={"t": {"runner": "direct"}},
        )
    )
    async with harness:
        run_id = await harness.submit("t", "q", idempotency_key="k")
        assert await harness.submit("t", "q", idempotency_key="k") == run_id
        events = [event async for event in harness.stream(run_id)]
        result = await harness.result(run_id)
    assert result.ok
    statuses = [e.status for e in events if e.type == "status"]
    assert statuses[0] is hw.RunStatus.PENDING
    assert statuses[-1] is hw.RunStatus.COMPLETED
    assert hw.RunStatus.RUNNING in statuses
    assert any(e.type == "trace" for e in events)
    assert [e.seq for e in events] == sorted(e.seq for e in events)


async def test_streaming_a_finished_run_replays_its_status_history(build: Builder) -> None:
    harness = build(spec(models=scripted({"text": "x"}), tasks={"t": {"runner": "direct"}}))
    result = await harness.run("t", "q")
    events = [event async for event in harness.stream(result.run_id)]
    assert [e.status for e in events] == [
        hw.RunStatus.PENDING,
        hw.RunStatus.RUNNING,
        hw.RunStatus.COMPLETED,
    ]
    assert [e async for e in harness.stream("run_unknown")] == []


async def test_chunks_and_approvals_are_streamed(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"chunks": ["a", "b"]}),
            middleware=[
                {
                    "use": "testkit.script",
                    "rules": [{"hook": "output.before", "outcome": "suspend"}],
                }
            ],
            tasks={"t": {"runner": {"use": "session", "handler": "hw_testkit:answer"}}},
        )
    )

    async def stream_answer(s: hw.Session, input: Any) -> Any:
        return await s.generate(messages=[hw.Message.user("q")], stream=True)

    import hw_testkit

    hw_testkit.stream_answer = stream_answer  # type: ignore[attr-defined]
    harness = build(
        spec(
            models=scripted({"chunks": ["a", "b"]}),
            middleware=[
                {
                    "use": "testkit.script",
                    "rules": [{"hook": "output.before", "outcome": "suspend"}],
                }
            ],
            tasks={"t": {"runner": {"use": "session", "handler": "hw_testkit:stream_answer"}}},
        )
    )
    async with harness:
        run_id = await harness.submit("t", "q")
        events = [event async for event in harness.stream(run_id)]
    chunks = [e.chunk.delta for e in events if e.chunk is not None]
    assert chunks == ["a", "b"]
    approvals = [e for e in events if e.type == "approval"]
    assert len(approvals) == 1
    assert events[-1].type == "approval"


async def test_cancelling_a_running_run(build: Builder) -> None:
    harness = build(spec(models=scripted({"wait": True}), tasks={"t": {"runner": "direct"}}))
    async with harness:
        run_id = await harness.submit("t", "q")
        with anyio.fail_after(5):
            while (await harness.result(run_id)).status is not hw.RunStatus.RUNNING:
                await anyio.lowlevel.checkpoint()
        result = await harness.cancel(run_id)
    assert result.status is hw.RunStatus.CANCELLED
    assert result.trace[-1].hook is hw.HookPoint.RUN_END


async def test_a_cancelled_caller_records_a_cancelled_run(build: Builder) -> None:
    harness = build(spec(models=scripted({"wait": True}), tasks={"t": {"runner": "direct"}}))
    with anyio.move_on_after(0.05):
        await harness.run("t", "q", idempotency_key="slow")
    again = await harness.run("t", "q", idempotency_key="slow")
    assert again.status is hw.RunStatus.CANCELLED


async def test_cancelling_a_run_that_is_not_live(build: Builder) -> None:
    harness = build(spec(models=scripted({"text": "x"}), tasks={"t": {"runner": "direct"}}))
    done = await harness.run("t", "q")
    assert (await harness.cancel(done.run_id)) == done
    with pytest.raises(NotFound):
        await harness.resume(done.run_id)
