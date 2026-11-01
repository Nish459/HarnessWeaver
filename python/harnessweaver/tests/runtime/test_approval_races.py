"""Answers that race for one pending approval: one wins, the rest find nothing (ADR-0044)."""

import json
import os
import sys
import textwrap
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest

import harnessweaver as hw
from harnessweaver.errors import NotFound

from .conftest import FIXTURES, Builder, write
from .test_approvals import FINANCE, refund_spec, suspended

pytestmark = pytest.mark.anyio

type Answer = Callable[[], Awaitable[hw.RunResult]]


def sqlite_spec(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    """The refund spec on a sqlite file every harness in a test shares."""
    return refund_spec(state={"use": "sqlite", "path": str(tmp_path / "state.db")}, **extra)


@pytest.fixture
async def opened(build: Builder) -> AsyncIterator[Builder]:
    """``build``, closing each harness's store when the test ends."""
    harnesses: list[hw.Harness] = []

    def make(document: dict[str, Any], **options: Any) -> hw.Harness:
        harnesses.append(build(document, **options))
        return harnesses[-1]

    yield make
    for harness in harnesses:
        await harness.aclose()


def meet_after_reading(*harnesses: hw.Harness, parties: int = 2) -> None:
    """Hold each answer until all have read the pending checkpoint, so they overlap for sure."""
    arrived = 0
    met = anyio.Event()

    def holding(read: Callable[[str], Awaitable[Any]]) -> Callable[[str], Awaitable[Any]]:
        async def read_then_meet(run_id: str) -> Any:
            nonlocal arrived
            found = await read(run_id)
            arrived += 1
            if arrived >= parties:
                met.set()
            await met.wait()
            return found

        return read_then_meet

    for harness in harnesses:
        state: Any = harness._state  # pyright: ignore[reportPrivateUsage]
        state.get_checkpoint = holding(state.get_checkpoint)


async def race(*answers: Answer) -> tuple[list[hw.RunResult], list[NotFound]]:
    """Run the answers at once; any error but NotFound fails the test."""
    won: list[hw.RunResult] = []
    lost: list[NotFound] = []

    async def one(answer: Answer) -> None:
        try:
            won.append(await answer())
        except NotFound as exc:
            lost.append(exc)

    async with anyio.create_task_group() as group:
        for answer in answers:
            group.start_soon(one, answer)
    return won, lost


def answering(harness: hw.Harness, first: hw.RunResult, decision: str) -> Answer:
    assert first.approval is not None
    approval_id = first.approval.approval_id

    async def answer() -> hw.RunResult:
        return await harness.approve(
            first.run_id,
            approval_id,
            decision,  # pyright: ignore[reportArgumentType]
            approver=FINANCE,
        )

    return answer


@pytest.mark.parametrize(
    "decisions",
    [("approve", "approve"), ("approve", "reject"), ("reject", "approve"), ("reject", "reject")],
)
@pytest.mark.parametrize("harnesses", [1, 2], ids=["one_harness", "two_harnesses"])
async def test_one_answer_wins_and_the_store_says_which(
    opened: Builder, testkit: Any, tmp_path: Path, decisions: tuple[str, str], harnesses: int
) -> None:
    document = sqlite_spec(tmp_path)
    one = opened(document)
    other = opened(document) if harnesses == 2 else one
    first = await suspended(one)
    meet_after_reading(*{id(h): h for h in (one, other)}.values())
    won, lost = await race(
        answering(one, first, decisions[0]), answering(other, first, decisions[1])
    )
    assert len(won) == 1
    assert len(lost) == 1
    result = won[0]
    executed = len(testkit.RECORDER.tool_calls)
    if result.status is hw.RunStatus.BLOCKED:
        assert executed == 0
    else:
        assert result.ok
        assert executed == 1
    assert (await other.result(first.run_id)).status is result.status


async def test_the_memory_store_also_lets_one_answer_win(build: Builder, testkit: Any) -> None:
    harness = build(refund_spec())
    first = await suspended(harness)
    meet_after_reading(harness)
    won, lost = await race(
        answering(harness, first, "approve"), answering(harness, first, "approve")
    )
    assert [r.ok for r in won] == [True]
    assert len(lost) == 1
    assert len(testkit.RECORDER.tool_calls) == 1


async def test_a_losing_answer_records_nothing(opened: Builder, tmp_path: Path) -> None:
    document = sqlite_spec(tmp_path)
    document["state"]["record"] = True
    one, other = opened(document), opened(document)
    first = await suspended(one)
    meet_after_reading(one, other)
    await race(answering(one, first, "approve"), answering(other, first, "reject"))
    recorded = await one._state.recording(first.run_id)  # pyright: ignore[reportPrivateUsage]
    assert len([call for call in recorded if call.kind == "approval"]) == 1


async def test_a_late_answer_to_an_expired_request_finds_nothing(
    opened: Builder, tmp_path: Path
) -> None:
    clock = hw.FakeClock()
    document = sqlite_spec(tmp_path)
    one, other = opened(document, clock=clock), opened(document, clock=clock)
    first = await suspended(one)
    assert first.approval is not None
    assert first.approval.expires_at is not None
    clock.advance(first.approval.expires_at - clock.now() + timedelta(seconds=1))
    meet_after_reading(one, other)
    won, lost = await race(answering(one, first, "approve"), answering(other, first, "approve"))
    assert [r.status for r in won] == [hw.RunStatus.ESCALATED]
    assert len(lost) == 1


async def test_cancel_and_an_answer_cannot_both_win(
    opened: Builder, testkit: Any, tmp_path: Path
) -> None:
    document = sqlite_spec(tmp_path)
    one, other = opened(document), opened(document)
    first = await suspended(one)
    meet_after_reading(one, other)
    won, _ = await race(answering(one, first, "approve"), lambda: other.cancel(first.run_id))
    stored = await one.result(first.run_id)
    if stored.status is hw.RunStatus.CANCELLED:
        assert testkit.RECORDER.tool_calls == []
    else:
        assert stored.ok
        assert len(testkit.RECORDER.tool_calls) == 1
    assert won  # whichever lost, nobody saw anything but a result or NotFound


async def test_an_answer_while_the_run_is_still_suspending_is_refused_untouched(
    build: Builder, testkit: Any
) -> None:
    """A channel can get an answer back before ``_suspend`` returns. It must not share the
    live run's scope, and must leave the request answerable."""
    harness = build(refund_spec())
    refused: list[type[Exception]] = []

    class Hasty:
        async def notify(self, approval: hw.ApprovalRequest, env: hw.Envelope) -> None:
            try:
                await harness.approve(approval.run_id, approval.approval_id, approver=FINANCE)
            except NotFound as exc:
                refused.append(type(exc))

    harness._approval_channel = Hasty()  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]
    first = await suspended(harness)
    assert refused == [NotFound]
    assert testkit.RECORDER.tool_calls == []
    assert first.approval is not None
    assert (await harness.approve(first.run_id, first.approval.approval_id, approver=FINANCE)).ok


ANSWER_IN_ANOTHER_PROCESS = textwrap.dedent(
    """
    import json, sys, time
    from pathlib import Path

    import anyio

    import harnessweaver as hw
    import hw_testkit
    from harnessweaver.core.registry import PluginCatalog
    from harnessweaver.errors import NotFound


    async def main(spec, run_id, approval_id, decision, meeting, me, parties):
        harness = hw.Harness.load(
            spec, clock=hw.FakeClock(), tools=hw_testkit.FakeTools(), catalog=PluginCatalog()
        )
        read = harness._state.get_checkpoint

        async def read_then_meet(run_id):
            found = await read(run_id)
            Path(meeting, me).touch()
            while len(list(Path(meeting).iterdir())) < parties:
                await anyio.sleep(0.01)
            return found

        harness._state.get_checkpoint = read_then_meet
        try:
            result = await harness.approve(
                run_id, approval_id, decision, approver=hw.Principal(id="bob", roles=("finance",))
            )
            status = result.status.value
        except NotFound:
            status = "not_found"
        print(json.dumps({"status": status, "executed": len(hw_testkit.RECORDER.tool_calls)}))


    anyio.run(main, *sys.argv[1:6], sys.argv[6], int(sys.argv[7]))
    """
)


@pytest.mark.parametrize("decisions", [("approve", "approve"), ("approve", "reject")])
async def test_answers_from_separate_processes_on_one_file(
    opened: Builder, testkit: Any, tmp_path: Path, decisions: tuple[str, str]
) -> None:
    """The real thing the in-process races stand in for: two OS processes, one sqlite file."""
    document = sqlite_spec(tmp_path)
    first = await suspended(opened(document))
    assert first.approval is not None
    approval_id = first.approval.approval_id
    meeting = tmp_path / "meeting"
    meeting.mkdir()
    env = {**os.environ, "PYTHONPATH": str(FIXTURES)}
    spec_path = str(write(tmp_path, document))
    answers: list[dict[str, Any]] = []

    async def answer_in_a_process(index: int, decision: str) -> None:
        done = await anyio.run_process(
            [
                sys.executable,
                "-c",
                ANSWER_IN_ANOTHER_PROCESS,
                spec_path,
                first.run_id,
                approval_id,
                decision,
                str(meeting),
                str(index),
                "2",
            ],
            env=env,
            check=False,
        )
        assert done.returncode == 0, done.stderr.decode()
        answers.append(json.loads(done.stdout))

    with anyio.fail_after(60):
        async with anyio.create_task_group() as group:
            for index, decision in enumerate(decisions):
                group.start_soon(answer_in_a_process, index, decision)
    assert sorted(a["status"] == "not_found" for a in answers) == [False, True]
    winner = next(a for a in answers if a["status"] != "not_found")
    assert sum(a["executed"] for a in answers) == (0 if winner["status"] == "blocked" else 1)
    assert (await opened(document).result(first.run_id)).status.value == winner["status"]
