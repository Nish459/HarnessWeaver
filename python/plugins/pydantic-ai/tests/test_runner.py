"""The ``pydantic_ai.agent`` runner: tasks run by Pydantic AI agents, governed (ADR-0037)."""

from pathlib import Path
from typing import Any

import pai_agents
import pytest
from pai_agents import RAN, calls, runner, spec, text

import harnessweaver as hw
from harnessweaver.errors import SpecError
from harnessweaver.testing import FakeTool, harness_for_test, output, reply, scripted, tool_call

pytestmark = pytest.mark.anyio

FINANCE = hw.Principal(id="bob", roles=("finance",))
AMOUNT = {
    "type": "object",
    "properties": {"amount_usd": {"type": "number"}},
    "required": ["amount_usd"],
}
ORDER = {"type": "object", "properties": {"order_id": {"type": "string"}}}


def refund_tool() -> FakeTool:
    return FakeTool(
        "refund",
        result=lambda args: {"refunded": args["amount_usd"]},
        description="Refund a payment.",
        input_schema=AMOUNT,
        governance={"approval": {"when": "args.amount_usd > 100", "approver_role": "finance"}},
    )


def manifests(*names: str, **governance: Any) -> list[FakeTool]:
    """Manifests for the agent's own tools; the agent runs them, never these fakes."""
    return [FakeTool(n, input_schema=ORDER, governance=governance) for n in names]


def app(agent: str, *replies: Any, tools: Any = (), **sections: Any) -> hw.Harness:
    tasks = {
        "t": {"runner": runner(agent, **sections.pop("settings", {})), **sections.pop("task", {})}
    }
    return harness_for_test(spec(tasks=tasks, **sections), model=scripted(*replies), tools=tools)


async def test_a_task_runs_on_the_harness_model() -> None:
    model = scripted(output({"category": "billing"}))
    harness = harness_for_test(spec(tasks={"t": {"runner": runner()}}), model=model)
    result = await harness.run("t", "I was charged twice")
    assert result.ok, result.error
    assert result.output == {"category": "billing"}
    assert pai_agents.hooks(result.run_id) == [
        "run.start",
        "input.before",
        "model.before",
        "model.after",
        "output.before",
        "run.end",
    ]
    (request,) = model.requests
    assert [(m.role, m.content) for m in request.messages] == [
        ("system", "Classify the message."),
        ("user", "I was charged twice"),
    ]
    assert request.output_schema is not None
    assert request.output_schema["title"] == "Answer"


async def test_the_task_prompt_and_tools_reach_the_agent(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "refunds@1.md").write_text("Refunds for {customer}.", encoding="ascii")
    document = spec(
        prompts={"dir": str(tmp_path / "prompts")},
        tasks={"t": {"runner": runner("helper"), "prompt": "refunds@1", "tools": ["refund"]}},
    )
    refund = refund_tool()
    model = scripted(tool_call("refund", amount_usd=5), "done")
    harness = harness_for_test(document, model=model, tools=[refund])
    result = await harness.run("t", {"customer": "alice"})
    assert result.ok, result.error
    assert result.output == "done"
    assert [c.arguments for c in refund.calls] == [{"amount_usd": 5}]
    first = model.requests[0]
    assert first.messages[0].content.startswith("Refunds for alice.")
    assert [t.name for t in first.tools] == ["lookup_order", "cancel_order", "courier", "refund"]
    assert [m.role for m in model.requests[1].messages][-1] == "tool"
    assert "tool.before" in pai_agents.hooks(result.run_id)


async def test_the_agents_own_tools_need_manifests() -> None:
    blocked = app("helper", tool_call("lookup_order", order_id="7"), "done")
    result = await blocked.run("t", "where is my order?")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "manifest_required"
    assert RAN == []
    governed = app(
        "helper", tool_call("lookup_order", order_id="7"), "done", tools=manifests("lookup_order")
    )
    result = await governed.run("t", "where is my order?")
    assert result.ok, result.error
    assert RAN == [("lookup_order", {"order_id": "7"})]  # the agent's function, not the fake


async def test_a_governed_approval_suspends_and_resumes(tmp_path: Path) -> None:
    refund = refund_tool()
    state = {"use": "sqlite", "path": str(tmp_path / "state.db")}
    document = spec(state=state, tasks={"t": {"runner": runner("helper"), "tools": ["refund"]}})
    first = harness_for_test(
        document, model=scripted(tool_call("refund", amount_usd=500), "done"), tools=[refund]
    )
    waiting = await first.run("t", "refund my order")
    assert waiting.status is hw.RunStatus.AWAITING_APPROVAL
    assert waiting.approval is not None
    assert waiting.approval.approver_role == "finance"
    assert refund.calls == []
    await first.aclose()
    # A new process: the agent continues from the checkpoint's message history.
    again = harness_for_test(document, model=scripted("done"), tools=[refund])
    done = await again.approve(
        waiting.run_id,
        waiting.approval.approval_id,
        "edit",
        approver=FINANCE,
        edited_args={"amount_usd": 50},
    )
    await again.aclose()
    assert done.ok, done.error
    assert done.output == "done"
    assert [c.arguments for c in refund.calls] == [{"amount_usd": 50}]


async def test_tools_marked_requires_approval_ask_the_harness() -> None:
    cancel = [{"name": "cancel_order", "arguments": {"order_id": i}} for i in ("7", "8")]
    replies = (reply(tool_calls=cancel), "done")
    harness = app("helper", *replies, tools=manifests("cancel_order"))
    waiting = await harness.run("t", "cancel both")
    assert waiting.approval is not None
    assert waiting.approval.reason == "the agent asks for approval to call cancel_order"
    assert waiting.approval.call is not None
    assert waiting.approval.call.arguments == {"order_id": "7"}
    second = await harness.approve(waiting.run_id, waiting.approval.approval_id, approver=FINANCE)
    assert RAN == [("cancel_order", {"order_id": "7"})]  # only what a human approved ran
    assert second.approval is not None
    assert second.approval.call is not None
    assert second.approval.call.arguments == {"order_id": "8"}
    done = await harness.approve(second.run_id, second.approval.approval_id, approver=FINANCE)
    assert done.ok, done.error
    assert RAN == [("cancel_order", {"order_id": "7"}), ("cancel_order", {"order_id": "8"})]


async def test_output_middleware_repairs_through_the_agent() -> None:
    rules = [{"id": "known", "when": "output.category == 'unknown'", "message": "pick a category"}]
    replies = (output({"category": "unknown"}), output({"category": "billing"}))
    harness = app("support", *replies, validation={"rules": rules})
    result = await harness.run("t", "hello")
    assert result.ok, result.error
    assert result.output == {"category": "billing"}
    repairs = [e.reason for e in result.trace if e.code == "repair"]
    assert repairs == ["repair 1: pick a category"]
    exhausted = await app("support", *replies[:1], validation={"rules": rules}).run("t", "hello")
    assert exhausted.status is hw.RunStatus.BLOCKED
    assert exhausted.error is not None
    assert exhausted.error.details["code"] == "validation_failed"
    escalating = {"rules": rules, "on_failure": "escalate", "max_repairs": 0}
    escalated = await app("support", *replies, validation=escalating).run("t", "hello")
    assert escalated.status is hw.RunStatus.ESCALATED


async def test_an_approved_output_is_still_validated() -> None:
    rules = [{"id": "known", "when": "output.category == 'unknown'", "message": "pick a category"}]
    reviewed = [{"use": "pai_test.review_answers"}]
    harness = app(
        "support", output({"category": "unknown"}), middleware=reviewed, validation={"rules": rules}
    )
    waiting = await harness.run("t", "hello")  # Suspend outranks Retry
    assert waiting.approval is not None
    done = await harness.approve(waiting.run_id, waiting.approval.approval_id, approver=FINANCE)
    assert done.status is hw.RunStatus.BLOCKED
    assert done.error is not None
    assert done.error.details["code"] == "validation_failed"


async def test_a_call_a_human_approved_runs_again_without_asking() -> None:
    cancel = reply(tool_calls=[{"name": "cancel_order", "arguments": {"order_id": "7"}}])
    harness = app("helper", cancel, cancel, "done", tools=manifests("cancel_order"))
    waiting = await harness.run("t", "cancel it, twice")
    assert waiting.approval is not None
    done = await harness.approve(waiting.run_id, waiting.approval.approval_id, approver=FINANCE)
    assert done.ok, done.error
    assert RAN == [("cancel_order", {"order_id": "7"})] * 2


async def test_an_output_can_wait_for_approval() -> None:
    reviewed = [{"use": "pai_test.audit"}, {"use": "pai_test.review_answers"}]
    harness = app("support", output({"category": "billing"}), middleware=reviewed)
    waiting = await harness.run("t", "hello")
    assert waiting.approval is not None
    assert waiting.approval.reason == "answers are reviewed"
    done = await harness.approve(waiting.run_id, waiting.approval.approval_id, approver=FINANCE)
    assert done.ok, done.error
    assert done.output == {"category": "billing"}


async def test_a_recorded_run_replays_without_running_tools(tmp_path: Path) -> None:
    state = {"use": "sqlite", "path": str(tmp_path / "state.db"), "record": True}
    harness = app(
        "helper",
        tool_call("lookup_order", order_id="7"),
        "done",
        tools=manifests("lookup_order"),
        state=state,
    )
    result = await harness.run("t", "where is my order?")
    report = await harness.replay(result.run_id)
    await harness.aclose()
    assert not report.differs
    assert (report.model_answers_used, report.missing_tool_results) == (2, 0)
    assert len(RAN) == 1


async def test_the_agents_own_model_and_deps() -> None:
    document = spec(
        tasks={"t": {"runner": runner("shop_agent", model="agent", deps="pai_agents:make_shop")}}
    )
    harness = harness_for_test(document, tools=manifests("shop_name"))

    def named(messages: list[Any], info: Any) -> Any:
        (returned,) = messages[-1].parts
        return text(f"at {returned.content}")

    with pai_agents.shop_agent.override(model=pai_agents.model(calls(("shop_name", {})), named)):
        result = await harness.run("t", "which shop?", tenant="acme")
    assert result.ok, result.error
    assert result.output == "at shop for acme"
    assert pai_agents.hooks(result.run_id)[2:4] == ["model.before", "model.after"]


async def test_what_the_runner_refuses() -> None:
    with pytest.raises(SpecError, match="isn't a Pydantic AI agent"):
        app("not_an_agent", "x")
    with pytest.raises(SpecError, match="can't import 'pai_agents:missing'"):
        app("missing", "x")
    with pytest.raises(SpecError, match="isn't callable"):
        app("support", "x", settings={"deps": "pai_agents:not_an_agent"})
    with pytest.raises(SpecError, match=r"isn't 'package\.module:attribute'"):
        harness_for_test(
            spec(tasks={"t": {"runner": {"use": "pydantic_ai.agent", "agent": "nope"}}})
        )
    external = await app(
        "helper", tool_call("courier", order_id="7"), tools=manifests("courier")
    ).run("t", "ship it")
    assert external.status is hw.RunStatus.FAILED
    assert external.error is not None
    assert "external execution" in external.error.message
