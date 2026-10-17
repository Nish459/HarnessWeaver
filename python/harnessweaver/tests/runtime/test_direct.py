"""The direct runner and the run lifecycle, end to end with a scripted model."""

from datetime import timedelta
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.trace import TraceKind
from harnessweaver.errors import BoundViolation, NotFound

from .conftest import Builder, scripted, spec

pytestmark = pytest.mark.anyio

SUMMARY = "hw_testkit:Summary"


def task(**fields: Any) -> dict[str, Any]:
    return {"runner": "direct", **fields}


def hooks_fired(result: hw.RunResult) -> list[str]:
    return [e.hook.value for e in result.trace if e.kind is TraceKind.HOOK and e.hook]


def script(*rules: dict[str, Any]) -> dict[str, Any]:
    return {"use": "testkit.script", "rules": list(rules)}


async def test_a_typed_answer_completes(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            models=scripted({"output": {"title": "Q3", "words": 3}}),
            tasks={"summarize": task(output=SUMMARY)},
        )
    )
    result = await harness.run("summarize", "summarize this", principal="alice")
    assert result.ok
    assert result.status is hw.RunStatus.COMPLETED
    assert result.output == {"title": "Q3", "words": 3}
    assert result.usage == hw.Usage(input_tokens=10, output_tokens=5)
    assert result.cost_usd is None
    assert result.cost_known is False
    assert hooks_fired(result) == [
        "run.start",
        "input.before",
        "model.before",
        "model.after",
        "output.before",
        "run.end",
    ]
    request = testkit.RECORDER.requests[0]
    assert request.output_schema is not None
    assert request.messages[-1].content == "summarize this"
    assert result.ended_at is not None


async def test_the_prompt_is_rendered_from_the_input(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(models=scripted({"text": "hi"}), tasks={"greet": task(prompt="greet@1")}),
        prompts={"greet@1": "Greet {name} politely."},
    )
    result = await harness.run("greet", {"name": "Ada"})
    assert result.output == "hi"
    system, user = testkit.RECORDER.requests[0].messages
    assert system.content == "Greet Ada politely."
    assert user.content == '{"name": "Ada"}'


async def test_the_tool_loop_runs_governed_tools(build: Builder, testkit: Any) -> None:
    call = {"id": "c1", "name": "lookup", "arguments": {"id": "42"}}
    harness = build(
        spec(
            models=scripted({"tool_calls": [call]}, after_tool={"text": "alice is gold"}),
            middleware=[{"use": "testkit.audit"}],
            tasks={"support": task(tools=["lookup"])},
        )
    )
    result = await harness.run("support", "who is customer 42?")
    assert result.output == "alice is gold"
    assert [c.name for c in testkit.RECORDER.tool_calls] == ["lookup"]
    first, second = testkit.RECORDER.requests
    assert [t.name for t in first.tools] == ["lookup"]
    assert second.messages[-1].role is hw.Role.TOOL
    assert "gold" in second.messages[-1].content
    labels = testkit.RECORDER.envelopes[-1].labels
    assert labels.untrusted_seen
    assert labels.private_seen
    assert labels.sources == ("tool:lookup",)
    assert "tool.before" in testkit.RECORDER.hooks
    assert "tool.after" in testkit.RECORDER.hooks


async def test_the_tool_loop_is_bounded(build: Builder) -> None:
    call = {"id": "c1", "name": "lookup", "arguments": {}}
    harness = build(
        spec(
            models=scripted({"tool_calls": [call]}),
            tasks={"loop": {"runner": {"use": "direct", "max_steps": 2}, "tools": ["lookup"]}},
        )
    )
    result = await harness.run("loop", "go")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "max_steps"


async def test_an_invalid_answer_is_repaired_once(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            models=scripted({"output": {"title": "Q3"}}, {"output": {"title": "Q3", "words": 2}}),
            tasks={"summarize": task(output=SUMMARY)},
        )
    )
    result = await harness.run("summarize", "text")
    assert result.output == {"title": "Q3", "words": 2}
    repair = testkit.RECORDER.requests[1].messages[-1]
    assert "words" in repair.content
    assert "not accepted" in repair.content


async def test_a_retry_at_output_before_repairs(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            models=scripted({"text": "short"}, {"text": "a longer answer"}),
            middleware=[
                script(
                    {"hook": "output.before", "outcome": "retry", "reason": "too short", "times": 1}
                )
            ],
            tasks={"answer": task()},
        )
    )
    result = await harness.run("answer", "q")
    assert result.output == "a longer answer"
    assert "too short" in testkit.RECORDER.requests[1].messages[-1].content


@pytest.mark.parametrize(
    ("on_failure", "status"), [("block", "blocked"), ("escalate", "escalated")]
)
async def test_repairs_run_out(build: Builder, on_failure: str, status: str) -> None:
    harness = build(
        spec(
            models=scripted({"text": "not json"}),
            validation={"max_repairs": 1, "on_failure": on_failure},
            tasks={"summarize": task(output=SUMMARY)},
        )
    )
    result = await harness.run("summarize", "text")
    assert result.status == status
    assert result.error is not None
    assert result.error.details["code"] == "validation_failed"


async def test_invalid_input_fails_the_run(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(models=scripted({"text": "x"}), tasks={"triage": task(input="hw_testkit:Ticket")})
    )
    result = await harness.run("triage", {"priority": 2})
    assert result.status is hw.RunStatus.FAILED
    assert result.error is not None
    assert result.error.code is hw.errors.ErrorCode.VALIDATION_FAILED
    assert testkit.RECORDER.requests == []
    assert "run.error" in hooks_fired(result)


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
