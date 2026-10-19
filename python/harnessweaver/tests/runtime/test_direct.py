"""The direct runner: typed answers, prompts, the bounded tool loop and repairs."""

from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.trace import TraceKind

from .conftest import Builder, scripted, spec
from .direct_support import SUMMARY, hooks_fired, script, task

pytestmark = pytest.mark.anyio


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
    notes = [e for e in result.trace if e.code == "repair"]
    assert [(n.kind, n.hook, n.source) for n in notes] == [
        (TraceKind.NOTE, hw.HookPoint.OUTPUT_BEFORE, "harness.validation")
    ]
    assert notes[0].reason == "repair 1: words: Field required"


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
