"""What an approval covers: one call or the run, and only the role that gave it (ADR-0045)."""

from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.registry import PluginCatalog
from harnessweaver.errors import PolicyDenied, SpecError
from harnessweaver.testing import FakeTool, harness_for_test, reply, scripted, text, tool_call

pytestmark = pytest.mark.anyio

BOB = hw.Principal(id="bob", roles=("helpdesk",))
TESSA = hw.Principal(id="tessa", roles=("treasury",))
OVER_100 = {"approval": {"when": "args.usd > 100", "approver_role": "treasury"}}
HELPDESK_FIRST = {
    "use": "testkit.script",
    "rules": [
        {
            "hook": "tool.before",
            "outcome": "suspend",
            "tool": "pay",
            "reason": "the help desk looks first",
            "approver_role": "helpdesk",
        }
    ],
}


def pay(**governance: Any) -> FakeTool:
    return FakeTool(
        "pay",
        result="paid",
        input_schema={"type": "object"},
        governance={"approval": {"when": "args.usd > 0"}, **governance},
    )


def app(tool: FakeTool, *replies: Any, grant_scope: str | None = None, **spec: Any) -> hw.Harness:
    document: dict[str, Any] = {
        "plugins": {"local": ["hw_testkit"]},
        "tasks": {"t": {"runner": "direct", "tools": ["pay"]}},
        **spec,
    }
    if grant_scope is not None:
        document.setdefault("approvals", {})["grant_scope"] = grant_scope
    return harness_for_test(
        document, model=scripted(*replies), tools=[tool], catalog=PluginCatalog()
    )


async def answer(
    harness: hw.Harness, waiting: hw.RunResult, approver: hw.Principal = TESSA, **options: Any
) -> hw.RunResult:
    assert waiting.approval is not None, waiting.error
    return await harness.approve(
        waiting.run_id, waiting.approval.approval_id, approver=approver, **options
    )


# --- No. 11: one approval, one call -------------------------------------------------------------


async def test_a_repeat_in_the_same_response_asks_again(testkit: Any) -> None:
    tool = pay()
    both = reply(
        tool_calls=[
            {"id": "a", "name": "pay", "arguments": {"usd": 5}},
            {"id": "b", "name": "pay", "arguments": {"usd": 5}},
        ]
    )
    harness = app(tool, both, text("done"))
    second = await answer(harness, await harness.run("t", "pay"))
    assert second.status is hw.RunStatus.AWAITING_APPROVAL
    assert [c.id for c in tool.calls] == ["a"]
    done = await answer(harness, second)
    assert done.ok, done.error
    assert [c.id for c in tool.calls] == ["a", "b"]


async def test_a_repeat_in_a_later_turn_asks_again(testkit: Any) -> None:
    tool = pay()
    harness = app(tool, tool_call("pay", usd=5), tool_call("pay", usd=5), text("done"))
    second = await answer(harness, await harness.run("t", "pay"))
    assert second.status is hw.RunStatus.AWAITING_APPROVAL
    assert len(tool.calls) == 1
    assert (await answer(harness, second)).ok
    assert len(tool.calls) == 2


async def test_another_suspension_doesnt_revive_a_spent_approval(testkit: Any) -> None:
    tool = pay()
    harness = app(
        tool,
        tool_call("pay", usd=5),
        tool_call("pay", usd=6),
        tool_call("pay", usd=5),
        text("done"),
    )
    asks_for_6 = await answer(harness, await harness.run("t", "pay"))
    asks_for_5_again = await answer(harness, asks_for_6)
    assert asks_for_5_again.status is hw.RunStatus.AWAITING_APPROVAL
    assert asks_for_5_again.approval is not None
    assert asks_for_5_again.approval.call is not None
    assert asks_for_5_again.approval.call.arguments == {"usd": 5}
    assert (await answer(harness, asks_for_5_again)).ok
    assert [c.arguments["usd"] for c in tool.calls] == [5, 6, 5]


async def test_a_run_wide_scope_lets_repeats_through(testkit: Any) -> None:
    tool = pay()
    harness = app(
        tool, tool_call("pay", usd=5), tool_call("pay", usd=5), text("done"), grant_scope="run"
    )
    done = await answer(harness, await harness.run("t", "pay"))
    assert done.ok, done.error
    assert len(tool.calls) == 2


async def test_the_scope_is_checked_when_the_spec_loads(testkit: Any) -> None:
    with pytest.raises(SpecError):
        app(pay(), text("done"), grant_scope="forever")


async def twice(session: hw.Session, input: Any) -> str:
    """A handler that makes the same call twice: each execution needs its own approval."""
    await session.tool("pay", usd=5)
    await session.tool("pay", usd=5)
    return "done"


async def then_another(session: hw.Session, input: Any) -> str:
    """A handler re-run for its second approval repeats its first, approved, call."""
    await session.tool("pay", usd=5)
    await session.tool("pay", usd=6)
    return "done"


async def test_a_rerun_handler_doesnt_ask_again_for_what_it_repeats(testkit: Any) -> None:
    tool = pay()
    runner = {"use": "session", "handler": f"{__name__}:then_another"}
    harness = app(tool, text("unused"), tasks={"t": {"runner": runner, "tools": ["pay"]}})
    asks_for_6 = await answer(harness, await harness.run("t", "pay"))
    assert asks_for_6.status is hw.RunStatus.AWAITING_APPROVAL
    done = await answer(harness, asks_for_6)
    assert done.ok, done.error  # two approvals, not a third for the repeated first call
    assert [c.arguments["usd"] for c in tool.calls] == [5, 5, 6]


async def test_a_handler_repeating_a_call_ends_after_one_approval_each(testkit: Any) -> None:
    tool = pay()
    runner = {"use": "session", "handler": f"{__name__}:twice"}
    harness = app(tool, text("unused"), tasks={"t": {"runner": runner, "tools": ["pay"]}})
    second = await answer(harness, await harness.run("t", "pay"))
    assert second.status is hw.RunStatus.AWAITING_APPROVAL
    assert (await answer(harness, second)).ok


async def one_call(session: hw.Session, inputs: Any) -> str:
    await session.tool("pay", usd=5)
    return "one"


async def two_calls(session: hw.Session, inputs: Any) -> str:
    await session.tool("pay", usd=5)
    await session.tool("pay", usd=5)
    return "two"


async def test_a_finished_workflow_step_keeps_its_approvals_to_itself(testkit: Any) -> None:
    tool = pay()
    runner = {
        "use": "workflow",
        "steps": [
            {"id": "first", "handler": f"{__name__}:one_call"},
            {"id": "second", "handler": f"{__name__}:two_calls", "needs": ["first"]},
        ],
    }
    harness = app(tool, text("unused"), tasks={"t": {"runner": runner, "tools": ["pay"]}})
    waiting = await harness.run("t", "pay")
    asked = 0
    while waiting.status is hw.RunStatus.AWAITING_APPROVAL:
        asked += 1
        waiting = await answer(harness, waiting)
    assert waiting.ok, waiting.error
    assert asked == 3  # one for the first step, one for each of the second's calls
    assert len(tool.calls) == 4  # the second step ran twice; the first didn't run again


# --- No. 12: the role the step needs ------------------------------------------------------------


async def test_another_askers_role_doesnt_satisfy_the_manifest(testkit: Any) -> None:
    tool = pay(**OVER_100)
    harness = app(tool, tool_call("pay", usd=900), text("done"), middleware=[HELPDESK_FIRST])
    first = await harness.run("t", "pay")
    assert first.approval is not None
    assert first.approval.approver_role == "helpdesk"
    second = await answer(harness, first, BOB)
    assert second.status is hw.RunStatus.AWAITING_APPROVAL
    assert second.approval is not None
    assert second.approval.approver_role == "treasury"
    assert tool.calls == []
    with pytest.raises(PolicyDenied):
        await answer(harness, second, BOB)
    done = await answer(harness, second, TESSA)
    assert done.ok, done.error
    assert len(tool.calls) == 1


async def test_an_edit_survives_the_second_approval(testkit: Any) -> None:
    tool = pay(**OVER_100)
    harness = app(tool, tool_call("pay", usd=5), text("done"), middleware=[HELPDESK_FIRST])
    first = await harness.run("t", "pay")
    second = await answer(harness, first, BOB, decision="edit", edited_args={"usd": 900})
    assert second.approval is not None
    assert second.approval.approver_role == "treasury"
    assert second.approval.call is not None
    assert second.approval.call.arguments == {"usd": 900}
    done = await answer(harness, second, TESSA)
    assert done.ok, done.error
    assert [c.arguments for c in tool.calls] == [{"usd": 900}]


async def test_a_call_under_the_rule_needs_one_approval(testkit: Any) -> None:
    tool = pay(**OVER_100)
    harness = app(tool, tool_call("pay", usd=5), text("done"), middleware=[HELPDESK_FIRST])
    done = await answer(harness, await harness.run("t", "pay"), BOB)
    assert done.ok, done.error
    assert len(tool.calls) == 1


async def test_a_second_approval_spends_the_first_too(testkit: Any) -> None:
    """The help desk's approval led to treasury's: a repeat asks the help desk again."""
    tool = pay(**OVER_100)
    harness = app(
        tool,
        tool_call("pay", usd=900),
        tool_call("pay", usd=900),
        text("done"),
        middleware=[HELPDESK_FIRST],
    )
    second = await answer(harness, await harness.run("t", "pay"), BOB)
    again = await answer(harness, second, TESSA)
    assert again.approval is not None
    assert again.approval.approver_role == "helpdesk"


async def test_the_spec_role_binds_when_the_manifest_names_none(testkit: Any) -> None:
    tool = pay()
    harness = app(
        tool,
        tool_call("pay", usd=900),
        text("done"),
        middleware=[HELPDESK_FIRST],
        approvals={"approver_role": "treasury"},
    )
    second = await answer(harness, await harness.run("t", "pay"), BOB)
    assert second.approval is not None
    assert second.approval.approver_role == "treasury"
    assert tool.calls == []
    assert (await answer(harness, second, TESSA)).ok


async def test_the_task_role_binds_before_the_spec_role(testkit: Any) -> None:
    tool = pay()
    task = {"runner": "direct", "tools": ["pay"], "approvals": {"approver_role": "treasury"}}
    harness = app(
        tool,
        tool_call("pay", usd=900),
        text("done"),
        tasks={"t": task},
        middleware=[HELPDESK_FIRST],
        approvals={"approver_role": "helpdesk"},
    )
    second = await answer(harness, await harness.run("t", "pay"), BOB)
    assert second.approval is not None
    assert second.approval.approver_role == "treasury"


async def test_nobody_is_singled_out_when_no_role_is_named(testkit: Any) -> None:
    tool = pay()
    harness = app(tool, tool_call("pay", usd=5), text("done"))
    done = await answer(harness, await harness.run("t", "pay"), hw.Principal(id="anyone"))
    assert done.ok, done.error


async def test_a_run_wide_grant_still_needs_the_role(testkit: Any) -> None:
    tool = pay(**OVER_100)
    harness = app(
        tool,
        tool_call("pay", usd=900),
        text("done"),
        grant_scope="run",
        middleware=[HELPDESK_FIRST],
    )
    second = await answer(harness, await harness.run("t", "pay"), BOB)
    assert second.status is hw.RunStatus.AWAITING_APPROVAL
    assert tool.calls == []
