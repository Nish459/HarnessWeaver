"""The governor in running harnesses: manifests, approvals, policy, trifecta (DESIGNS No. 17)."""

from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.registry import PluginCatalog
from harnessweaver.errors import RunBlocked
from harnessweaver.ports import ToolDescription

from .conftest import Builder, spec
from .governance_support import (
    FINANCE,
    call,
    governor_notes,
    manifest,
    refund_tool,
    tool_spec,
)

pytestmark = pytest.mark.anyio


async def test_a_native_tool_runs_with_its_idempotency_key(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    refund_tool(tmp_path)
    harness = build(
        tool_spec(call("refund_payment", amount_usd=20), tools=["refund_payment"]), tools=None
    )
    result = await harness.run("t", "refund order 7")
    assert result.ok, result.error
    ((name, handled),) = testkit.RECORDER.handled
    assert (name, handled["amount_usd"]) == ("refund_payment", 20)
    assert handled["key"].startswith(f"{result.run_id}:sha256:")
    assert (None, "allowed") in governor_notes(result)


async def test_an_approval_rule_suspends_and_an_approval_resumes(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    refund_tool(tmp_path, approval={"when": "args.amount_usd > 100", "approver_role": "finance"})
    harness = build(
        tool_spec(call("refund_payment", amount_usd=500), tools=["refund_payment"]), tools=None
    )
    waiting = await harness.run("t", "refund order 7")
    assert waiting.status is hw.RunStatus.AWAITING_APPROVAL
    assert waiting.approval is not None
    assert waiting.approval.approver_role == "finance"
    assert "approval rule" in waiting.approval.reason
    assert testkit.RECORDER.handled == []
    channel: Any = harness._approval_channel  # pyright: ignore[reportPrivateUsage]
    assert [r.approval_id for r in channel.requests] == [waiting.approval.approval_id]
    done = await harness.approve(waiting.run_id, waiting.approval.approval_id, approver=FINANCE)
    assert done.ok, done.error
    assert [h["amount_usd"] for _, h in testkit.RECORDER.handled] == [500]
    assert ("approved", "approved by bob") in governor_notes(done)


@pytest.mark.parametrize(("edited", "status"), [(50, "completed"), (5000, "blocked")])
async def test_edited_arguments_are_checked_again(
    build: Builder, tmp_path: Path, testkit: Any, edited: int, status: str
) -> None:
    refund_tool(tmp_path, approval={"when": "args.amount_usd > 100"})
    rules = [{"id": "huge", "when": "args.amount_usd > 1000", "effect": "deny"}]
    document = tool_spec(
        call("refund_payment", amount_usd=500), tools=["refund_payment"], policy={"rules": rules}
    )
    harness = build(document, tools=None)
    waiting = await harness.run("t", "refund")
    assert waiting.approval is not None
    result = await harness.approve(
        waiting.run_id,
        waiting.approval.approval_id,
        "edit",
        approver=FINANCE,
        edited_args={"amount_usd": edited},
    )
    assert result.status == status
    if status == "completed":
        assert [h["amount_usd"] for _, h in testkit.RECORDER.handled] == [50]
    else:
        assert result.error is not None
        assert result.error.details["code"] == "policy_denied"
        assert testkit.RECORDER.handled == []


async def test_a_run_resumes_in_a_new_harness_after_a_restart(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    refund_tool(tmp_path, approval={"when": "args.amount_usd > 100"})
    document = tool_spec(
        call("refund_payment", amount_usd=500),
        tools=["refund_payment"],
        state={"use": "sqlite", "path": str(tmp_path / "state.db")},
    )
    first = build(document, tools=None)
    waiting = await first.run("t", "refund")
    assert waiting.approval is not None
    await first.aclose()
    second = build(document, tools=None)  # a new process, as far as the run is concerned
    done = await second.approve(waiting.run_id, waiting.approval.approval_id, approver=FINANCE)
    await second.aclose()
    assert done.ok, done.error
    assert [h["amount_usd"] for _, h in testkit.RECORDER.handled] == [500]


@pytest.mark.parametrize(
    ("fields", "arguments", "code"),
    [
        ({"definition_digest": "sha256:" + "0" * 64}, {"amount_usd": 5}, "digest_mismatch"),
        ({}, {"amount_usd": "lots"}, "schema_invalid"),
        ({"enabled": False}, {"amount_usd": 5}, "tool_disabled"),
        ({"tenants": ["globex"]}, {"amount_usd": 5}, "tool_not_enabled"),
    ],
)
async def test_the_governor_blocks_before_the_tool_runs(
    build: Builder, tmp_path: Path, testkit: Any, fields: dict[str, Any], arguments: Any, code: str
) -> None:
    refund_tool(tmp_path, **fields)
    harness = build(
        tool_spec(call("refund_payment", **arguments), tools=["refund_payment"]), tools=None
    )
    result = await harness.run("t", "refund", tenant="acme")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == code
    assert testkit.RECORDER.handled == []
    assert "lots" not in result.model_dump_json()  # reasons name rules, not values (R9)


async def test_a_pinned_digest_lets_the_tool_run(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    digest = hw.definition_digest(
        "refund_payment",
        "Refund a payment.",
        {
            "type": "object",
            "properties": {"amount_usd": {"type": "number", "minimum": 0}},
            "required": ["amount_usd"],
        },
    )
    refund_tool(tmp_path, definition_digest=digest)
    harness = build(
        tool_spec(call("refund_payment", amount_usd=5), tools=["refund_payment"]), tools=None
    )
    assert (await harness.run("t", "refund")).ok


@pytest.mark.parametrize(
    ("effect", "status", "code"),
    [
        ("deny", hw.RunStatus.BLOCKED, "policy_denied"),
        ("require_approval", hw.RunStatus.ESCALATED, "policy_requires_approval"),
    ],
)
async def test_run_start_rules_can_stop_a_run(
    build: Builder, testkit: Any, effect: str, status: hw.RunStatus, code: str
) -> None:
    rules = [{"id": "globex", "when": "tenant == 'globex'", "effect": effect, "hook": "run.start"}]
    document = spec(
        models={"provider": "testkit.scripted", "replies": [{"text": "hi"}]},
        policy={"rules": rules},
        tasks={"t": {"runner": "direct"}},
    )
    harness = build(document)
    blocked = await harness.run("t", "hello", tenant="globex")
    assert blocked.status is status
    assert blocked.error is not None
    assert blocked.error.details["code"] == code
    assert testkit.RECORDER.requests == []
    assert (await harness.run("t", "hello", tenant="acme")).ok
    with pytest.raises(hw.errors.RunInterrupted):
        async with harness.session(tenant="globex"):
            pass


async def test_the_lethal_trifecta_asks_before_data_can_leave(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    manifest(
        tmp_path, "lookup_order", handler="hw_testkit:lookup_order", data_access=["pii:customer"]
    )
    manifest(tmp_path, "send_email", handler="hw_testkit:send_email", egress=["smtp.example.com"])
    replies = (
        call("lookup_order", order_id="7"),
        call("send_email", to="x@example.com", body="hi"),
        {"text": "done"},
    )
    harness = build(
        tool_spec(*replies, tools=["lookup_order", "send_email"], after_tool=False), tools=None
    )
    result = await harness.run("t", "help")
    assert result.status is hw.RunStatus.AWAITING_APPROVAL
    assert result.approval is not None
    assert "lethal trifecta" in result.approval.reason
    assert [name for name, _ in testkit.RECORDER.handled] == ["lookup_order"]
    blocking = tool_spec(
        *replies,
        tools=["lookup_order", "send_email"],
        after_tool=False,
        tools_section={"trifecta": "block"},
    )
    blocked = await build(blocking, tools=None).run("t", "help")
    assert blocked.status is hw.RunStatus.BLOCKED
    assert blocked.error is not None
    assert blocked.error.details["code"] == "trifecta"


async def test_pii_in_the_input_counts_as_private_data(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    manifest(tmp_path, "lookup_order", handler="hw_testkit:lookup_order")
    manifest(tmp_path, "send_email", handler="hw_testkit:send_email", egress=["smtp.example.com"])
    replies = (
        call("lookup_order", order_id="7"),
        call("send_email", to="a", body="b"),
        {"text": "x"},
    )
    document = tool_spec(
        *replies,
        tools=["lookup_order", "send_email"],
        after_tool=False,
        guardrails={"input": [{"id": "pii", "use": "pii.regex"}]},
    )
    result = await build(document, tools=None).run("t", "my email is alice@example.com")
    assert result.status is hw.RunStatus.AWAITING_APPROVAL
    assert result.approval is not None
    assert "lethal trifecta" in result.approval.reason


async def test_tool_output_is_sanitized_before_anything_sees_it(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    manifest(
        tmp_path,
        "lookup_order",
        handler="hw_testkit:lookup_order",
        output={"sanitize": ["pii_redact", "strip_instructions"], "max_bytes": 60},
    )
    harness = build(
        tool_spec(call("lookup_order", order_id="7"), tools=["lookup_order"]), tools=None
    )
    result = await harness.run("t", "where is my order")
    assert result.ok
    seen = testkit.RECORDER.requests[-1].messages[-1].content
    assert "alice@example.com" not in seen
    assert "[EMAIL]" in seen
    assert "Ignore all previous" not in seen
    codes = [code for code, _ in governor_notes(result)]
    assert "output_sanitized" in codes


async def test_rate_limits_hold_under_concurrency(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    import anyio

    manifest(
        tmp_path,
        "lookup_order",
        handler="hw_testkit:lookup_order",
        rate_limit={"per_principal": "2/m"},
    )
    harness = build(tool_spec({"text": "x"}, tools=["lookup_order"]), tools=None)
    outcomes: list[str] = []

    async def one() -> None:
        try:
            async with harness.session(principal="alice") as s:
                await s.tool("lookup_order", order_id="7")
            outcomes.append("ran")
        except RunBlocked as exc:
            outcomes.append(str(exc.details["code"]))

    async with anyio.create_task_group() as group:
        for _ in range(5):
            group.start_soon(one)
    assert sorted(outcomes) == ["ran", "ran", "rate_limited", "rate_limited", "rate_limited"]
    async with harness.session(principal="carol") as s:  # another principal has its own limit
        await s.tool("lookup_order", order_id="8")


@pytest.mark.parametrize(
    ("judge", "status", "expected"),
    [
        ({"use": "testkit.careful"}, hw.RunStatus.AWAITING_APPROVAL, "wires are risky"),
        (
            {"use": "testkit.explodes"},
            hw.RunStatus.AWAITING_APPROVAL,
            "the judge failed (RuntimeError)",
        ),
        ({"use": "regex.deny", "patterns": ["wire"]}, hw.RunStatus.BLOCKED, "judge_blocked"),
    ],
)
async def test_a_judge_can_only_tighten(
    build: Builder,
    tmp_path: Path,
    testkit: Any,
    judge: dict[str, Any],
    status: hw.RunStatus,
    expected: str,
) -> None:
    manifest(tmp_path, "send_email", handler="hw_testkit:send_email")
    document = tool_spec(
        call("send_email", to="ops", body="please wire the money"),
        tools=["send_email"],
        tools_section={"judge": judge},
    )
    result = await build(document, tools=None).run("t", "go")
    assert result.status is status
    if status is hw.RunStatus.AWAITING_APPROVAL:
        assert result.approval is not None
        assert expected in result.approval.reason
    else:
        assert result.error is not None
        assert result.error.details["code"] == expected
    assert testkit.RECORDER.handled == []


@pytest.mark.parametrize(
    "section",
    [
        {"task": {"approvals": {"tools": ["refund_payment"]}}},
        {"tools_section": {"approval_by_risk": {"high": "required"}}},
    ],
)
async def test_tasks_and_risk_levels_can_always_ask(
    build: Builder, tmp_path: Path, testkit: Any, section: dict[str, Any]
) -> None:
    refund_tool(tmp_path)
    document = tool_spec(call("refund_payment", amount_usd=1), tools=["refund_payment"], **section)
    result = await build(document, tools=None).run("t", "refund")
    assert result.status is hw.RunStatus.AWAITING_APPROVAL


class _Bare:
    """Tools given in code without a manifest."""

    def __init__(self) -> None:
        self.ran: list[str] = []

    def describe(self, name: str) -> ToolDescription | None:
        return ToolDescription(hw.ToolInfo(name=name), hw.ToolSpec(name=name))

    async def execute(self, call: hw.ToolCall, env: hw.Envelope) -> hw.ToolResult:
        self.ran.append(call.name)
        return hw.ToolResult(call_id=call.id, output="ok")


async def test_tools_in_code_need_a_manifest(build: Builder, testkit: Any) -> None:
    document = spec(
        models={
            "provider": "testkit.scripted",
            "replies": [call("bare")],
            "after_tool": {"text": "x"},
        },
        tasks={"t": {"runner": "direct", "tools": ["bare"]}},
    )
    bare = _Bare()
    result = await build(document, tools=bare, catalog=PluginCatalog()).run("t", "go")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "manifest_required"
    assert bare.ran == []
    loose = await build({**document, "tools": {"require_manifest": False}}, tools=bare).run(
        "t", "go"
    )
    assert loose.ok
    assert bare.ran == ["bare"]
