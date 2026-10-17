"""Hook bus details beyond the shared ``bus`` fixtures, and the run context basics."""

from datetime import timedelta
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.budgets import BudgetMeter
from harnessweaver.core.bus import HookBus
from harnessweaver.core.context import RunContext
from harnessweaver.core.middleware import Registration
from harnessweaver.core.trace import RunTrace, TraceKind
from harnessweaver.errors import RunBlocked, SpecError

pytestmark = pytest.mark.anyio


async def keep(event: Any, env: hw.Envelope) -> hw.Outcome | None:
    return None


def registration(name: str, band: hw.Band, *, tasks: frozenset[str] | None = None) -> Registration:
    return Registration(
        name=name,
        handler=keep,
        hooks=frozenset({hw.HookPoint.TOOL_BEFORE, hw.HookPoint.TOOL_AFTER}),
        band=band,
        fail_mode="closed",
        tasks=tasks,
    )


def context(bus: HookBus, **kwargs: Any) -> RunContext:
    clock = hw.FakeClock()
    envelope = hw.Envelope.new(tenant="t", principal="p", clock=clock, **kwargs)
    return RunContext(
        envelope=envelope, bus=bus, trace=RunTrace(clock), meter=BudgetMeter(envelope.budget)
    )


async def test_task_scoped_middleware_and_bands() -> None:
    bus = HookBus(
        [
            registration("all", hw.Band.APP),
            registration("only-a", hw.Band.TASK, tasks=frozenset({"a"})),
            registration("base", hw.Band.BASELINE),
        ]
    )
    assert [r.name for r in bus.chain(hw.HookPoint.TOOL_BEFORE, "a")] == ["base", "all", "only-a"]
    assert [r.name for r in bus.chain(hw.HookPoint.TOOL_AFTER, "b")] == ["all", "base"]
    assert bus.chain(hw.HookPoint.RUN_START) == []
    assert bus.hooks_in_band(hw.Band.TASK, "a") == {
        hw.HookPoint.TOOL_BEFORE,
        hw.HookPoint.TOOL_AFTER,
    }
    assert bus.hooks_in_band(hw.Band.TASK, "b") == frozenset()
    assert len(bus.registrations) == 3


async def test_the_event_must_match_the_hook() -> None:
    bus = HookBus()
    env = hw.Envelope.new(tenant="t", principal="p")
    with pytest.raises(TypeError, match="carries"):
        await bus.emit(
            hw.HookPoint.RUN_START, hw.InputEvent(input="x"), env, RunTrace(hw.FakeClock())
        )


async def test_a_baseline_registration_must_fail_closed() -> None:
    with pytest.raises(SpecError, match="R2"):
        HookBus(
            [
                Registration(
                    "lax", keep, frozenset({hw.HookPoint.RUN_START}), hw.Band.BASELINE, "open"
                )
            ]
        )


async def test_the_context_is_current_only_while_active() -> None:
    ctx = context(HookBus())
    assert hw.current_run() is None
    with ctx.activate() as active:
        assert hw.current_run() is active
    assert hw.current_run() is None
    assert ctx.task_name is None
    assert ctx.clock.now() == hw.FakeClock().now()


async def test_a_context_without_a_provider_or_tools() -> None:
    ctx = context(HookBus())
    with pytest.raises(SpecError, match=r"models\.provider"):
        await ctx.generate(hw.ModelRequest(messages=(hw.Message.user("x"),)))
    with pytest.raises(SpecError, match="isn't registered"):
        ctx.tool_specs(["lookup"])
    with pytest.raises(RunBlocked, match="isn't registered"):
        await ctx.call_tool(hw.ToolCall(id="c", name="lookup"))


async def test_a_passed_deadline_stops_the_next_hook() -> None:
    clock = hw.FakeClock()
    envelope = hw.Envelope.new(
        tenant="t", principal="p", clock=clock, budget=hw.Budget(deadline=timedelta(seconds=1))
    )
    ctx = RunContext(
        envelope=envelope, bus=HookBus(), trace=RunTrace(clock), meter=BudgetMeter(envelope.budget)
    )
    assert await ctx.check_input("x") == "x"
    clock.advance("2s")
    with pytest.raises(hw.errors.DeadlineExceeded):
        await ctx.check_input("x")


async def test_the_trace_records_notes_and_hooks() -> None:
    trace = RunTrace(hw.FakeClock())
    trace.note("harness", "hello", details={"n": 1})
    assert trace.for_hook(hw.HookPoint.RUN_START) == []
    trace.hook(hw.HookPoint.RUN_START, "harness", hw.Continue(note="ok"), middleware=0)
    assert trace.hooks_fired() == [hw.HookPoint.RUN_START]
    assert [e.kind for e in trace] == [TraceKind.NOTE, TraceKind.HOOK]
    assert trace.events[1].reason == "ok"
