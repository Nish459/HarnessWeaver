"""Direct runs within limits: aliases, prices and budgets, deadlines, idempotency."""

from typing import Any

import pytest

import harnessweaver as hw

from .conftest import Builder, scripted, spec
from .direct_support import hooks_fired, task

pytestmark = pytest.mark.anyio


async def test_aliases_resolve_and_allow_lists_apply(build: Builder, testkit: Any) -> None:
    models = scripted({"text": "x"}, default="fast", aliases={"fast": "small-1", "strong": "big-2"})
    harness = build(spec(models=models, tasks={"a": task(), "b": task(model="strong")}))
    await harness.run("a", "q")
    await harness.run("b", "q")
    assert [(r.alias, r.model) for r in testkit.RECORDER.requests] == [
        ("fast", "small-1"),
        ("strong", "big-2"),
    ]
    limited = build(
        spec(models={**models, "allowed_aliases": ["fast"]}, tasks={"b": task(model="strong")})
    )
    result = await limited.run("b", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "model_not_allowed"


async def test_prices_give_a_cost_and_budgets_block(build: Builder, testkit: Any) -> None:
    call = {"id": "c1", "name": "lookup", "arguments": {}}
    harness = build(
        spec(
            models=scripted(
                {
                    "tool_calls": [call],
                    "model": "m1",
                    "usage": {"input_tokens": 1000, "output_tokens": 1000},
                },
                prices={"m1": {"input_per_mtok": 1, "output_per_mtok": 2}},
            ),
            budgets={"per_run": {"max_model_calls": 1}},
            tasks={"loop": task(tools=["lookup"])},
        )
    )
    result = await harness.run("loop", "go")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details == {
        "hook": "model.before",
        "code": "budget_exceeded",
        "limit": "max_model_calls",
    }
    assert result.cost_usd == pytest.approx(0.003)
    assert result.cost_known
    notes = [e for e in result.trace if e.source == "harness.budget"]
    assert notes[0].details["cost_source"] == "prices"
    assert notes[-1].code == "budget_exceeded"


async def test_the_deadline_fails_a_stuck_run(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"wait": True}),
            budgets={"per_run": {"deadline": "50ms"}},
            tasks={"slow": task()},
        )
    )
    result = await harness.run("slow", "q")
    assert result.status is hw.RunStatus.FAILED
    assert result.error is not None
    assert result.error.code is hw.errors.ErrorCode.DEADLINE_EXCEEDED
    assert hooks_fired(result)[-2:] == ["run.error", "run.end"]


async def test_the_deadline_follows_the_injected_clock(build: Builder, testkit: Any) -> None:
    clock = hw.FakeClock()

    class SlowTools(testkit.FakeTools):  # type: ignore[name-defined]
        async def execute(self, call: hw.ToolCall, env: hw.Envelope) -> hw.ToolResult:
            clock.advance("2m")
            return await super().execute(call, env)

    call = {"id": "c1", "name": "lookup", "arguments": {}}
    harness = build(
        spec(
            models=scripted({"tool_calls": [call]}, after_tool={"text": "done"}),
            budgets={"per_run": {"deadline": "1m"}},
            tasks={"t": task(tools=["lookup"])},
        ),
        clock=clock,
        tools=SlowTools(),
    )
    result = await harness.run("t", "q")
    assert result.status is hw.RunStatus.FAILED
    assert result.error is not None
    assert result.error.code is hw.errors.ErrorCode.DEADLINE_EXCEEDED


async def test_an_idempotency_key_returns_the_first_result(build: Builder, testkit: Any) -> None:
    harness = build(spec(models=scripted({"text": "once"}), tasks={"t": task()}))
    first = await harness.run("t", "q", idempotency_key="upload-1")
    second = await harness.run("t", "q", idempotency_key="upload-1")
    other = await harness.run("t", "q", idempotency_key="upload-1", tenant="other")
    assert second.run_id == first.run_id
    assert other.run_id != first.run_id
    assert len(testkit.RECORDER.requests) == 2


async def test_a_provider_failure_is_classified(build: Builder) -> None:
    harness = build(spec(models=scripted({"fail": True}), tasks={"t": task()}))
    result = await harness.run("t", "q")
    assert result.status is hw.RunStatus.FAILED
    assert result.error is not None
    assert result.error.code is hw.errors.ErrorCode.PROVIDER_ERROR
    assert result.error.retryable
    assert "upstream" not in result.error.message  # R9: only the exception type
