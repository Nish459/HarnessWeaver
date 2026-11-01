"""Outcomes at each hook point of a direct run, and how they are traced (R13)."""

from datetime import timedelta
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.trace import TraceKind
from harnessweaver.errors import BoundViolation, NotFound

from .conftest import Builder, scripted, spec
from .direct_support import hooks_fired, script, task

pytestmark = pytest.mark.anyio


async def test_a_block_at_run_start_stops_everything(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[
                script({"hook": "run.start", "outcome": "block", "reason": "closed today"})
            ],
            tasks={"t": task()},
        )
    )
    result = await harness.run("t", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.message == "closed today"
    assert testkit.RECORDER.requests == []
    assert hooks_fired(result) == ["run.start", "run.end"]


async def test_input_is_redacted_before_the_model_sees_it(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[
                script({"hook": "input.before", "outcome": "modify", "value": "[REDACTED]"})
            ],
            tasks={"t": task()},
        )
    )
    await harness.run("t", "my card is 4111")
    assert testkit.RECORDER.requests[0].messages[-1].content == "[REDACTED]"


async def test_a_retry_at_model_after_reasks_once(build: Builder, testkit: Any) -> None:
    once = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[script({"hook": "model.after", "outcome": "retry", "times": 1})],
            tasks={"t": task()},
        )
    )
    assert (await once.run("t", "q")).ok
    assert len(testkit.RECORDER.requests) == 2
    always = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[script({"hook": "model.after", "outcome": "retry"})],
            tasks={"t": task()},
        )
    )
    result = await always.run("t", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "retry_exhausted"


async def test_retry_where_it_isnt_supported_blocks(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[script({"hook": "input.before", "outcome": "retry"})],
            tasks={"t": task()},
        )
    )
    result = await harness.run("t", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "retry_not_supported"


async def test_suspend_where_it_isnt_supported_escalates(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[script({"hook": "model.before", "outcome": "suspend"})],
            tasks={"t": task()},
        )
    )
    result = await harness.run("t", "q")
    assert result.status is hw.RunStatus.ESCALATED


async def test_a_tool_the_task_didnt_offer_is_blocked(build: Builder, testkit: Any) -> None:
    """Two tasks share the registered tools: the model in one calls the other's tool."""
    refund = {"id": "c1", "name": "refund", "arguments": {"amount": 5}}
    harness = build(
        spec(
            models=scripted({"tool_calls": [refund]}, after_tool={"text": "done"}),
            tasks={
                "triage": task(tools=["lookup"]),
                "refunds": task(tools=["refund"], approvals={"tools": ["refund"]}),
            },
        )
    )
    result = await harness.run("triage", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "tool_not_offered"
    assert testkit.RECORDER.tool_calls == []
    assert "tool.before" not in hooks_fired(result)
    assert any(e.code == "tool_not_offered" for e in result.trace)  # R13


async def test_unknown_and_failing_tools(build: Builder, testkit: Any) -> None:
    unknown = {"id": "c1", "name": "nope", "arguments": {}}
    harness = build(spec(models=scripted({"tool_calls": [unknown]}), tasks={"t": task()}))
    result = await harness.run("t", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "tool_unknown"

    crash = {"id": "c2", "name": "crash", "arguments": {}}
    harness = build(
        spec(
            models=scripted({"tool_calls": [crash]}, after_tool={"text": "sorry"}),
            tasks={"t": task(tools=["crash"])},
        )
    )
    result = await harness.run("t", "q")
    assert result.output == "sorry"
    assert '"ValueError"' in testkit.RECORDER.requests[-1].messages[-1].content
    dumped = result.model_dump_json()
    assert "secret detail" not in dumped  # R9


async def test_unknown_tasks_and_budget_overrides(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            budgets={"per_run": {"max_model_calls": 5}},
            tasks={"t": task(budget={"overridable": ["max_model_calls"]}), "fixed": task()},
        )
    )
    with pytest.raises(NotFound):
        await harness.run("missing", "q")
    with pytest.raises(BoundViolation):
        await harness.run("fixed", "q", budget={"max_model_calls": 1})
    result = await harness.run("t", "q", budget={"max_model_calls": 0})
    assert result.status is hw.RunStatus.BLOCKED


async def test_every_outcome_is_traced(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[{"use": "testkit.audit"}, {"use": "testkit.flaky"}],
            tasks={"t": task()},
        )
    )
    result = await harness.run("t", "q")
    assert result.ok
    audited = [e.hook.value for e in result.trace if e.source == "testkit.audit" and e.hook]
    assert audited == testkit.RECORDER.hooks
    failure = next(e for e in result.trace if e.kind is TraceKind.FAILURE)
    assert failure.source == "testkit.flaky"
    assert failure.details == {"error_type": "RuntimeError", "timed_out": False}
    assert [e.seq for e in result.trace] == list(range(len(result.trace)))


async def test_a_block_at_run_end_withholds_the_output(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[script({"hook": "run.end", "outcome": "block", "reason": "audit failed"})],
            tasks={"t": task()},
        )
    )
    result = await harness.run("t", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.output is None


async def test_run_error_middleware_can_reclassify(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"fail": True}),
            middleware=[script({"hook": "run.error", "outcome": "retry"})],
            tasks={"t": task()},
        )
    )
    result = await harness.run("t", "q")
    assert result.status is hw.RunStatus.FAILED
    assert any("run.error isn't supported" in (e.reason or "") for e in result.trace)


async def test_results_and_explain(build: Builder) -> None:
    harness = build(spec(models=scripted({"text": "x"}), tasks={"t": task()}))
    result = await harness.run("t", "q")
    assert await harness.result(result.run_id) == result
    with pytest.raises(NotFound):
        await harness.result("run_missing")
    assert harness.name == "test-app"
    assert harness.tasks == ["t"]
    assert any(row.path == "models.provider" for row in harness.explain())
    assert harness.hooks()[hw.HookPoint.RUN_START] == []
    assert harness.spec.spec.metadata.name == "test-app"
    assert {p.plugin.namespace for p in harness.registry.plugins()} >= {"testkit", "harnessweaver"}


async def test_a_middleware_timeout_from_the_spec(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[
                {
                    **script({"hook": "input.before", "outcome": "wait"}),
                    "timeout": "20ms",
                    "hooks": ["input.before"],
                }
            ],
            tasks={"t": task()},
        )
    )
    result = await harness.run("t", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "middleware_timeout"


async def test_time_left_resets_the_deadline_budget(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            budgets={"per_run": {"deadline": "5m"}},
            tasks={"t": task()},
        )
    )
    result = await harness.run("t", "q")
    assert result.ok
    assert result.started_at is not None
    assert result.ended_at is not None
    assert result.ended_at - result.started_at == timedelta(0)
