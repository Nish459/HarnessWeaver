"""The support desk's tests: offline, with no network and no model spend."""

from pathlib import Path

import pytest
from helpdesk.models import Ticket

import harnessweaver as hw
from harnessweaver.testing import (
    assert_no_content,
    assert_trace,
    harness_for_test,
    output,
    scripted,
    step,
    tool_call,
)

pytestmark = pytest.mark.anyio

SPEC = Path(__file__).resolve().parents[1] / "harness.yaml"
BILLING = {"category": "billing", "priority": 2, "summary": "Charged twice; wants a refund."}


async def test_triage_returns_a_typed_answer() -> None:
    async with harness_for_test(SPEC, model=scripted(output(BILLING))) as harness:
        result = await harness.run("triage", Ticket(text="I was charged twice."))
    assert result.ok
    assert result.output == BILLING


async def test_a_rule_breaking_answer_is_repaired_once() -> None:
    model = scripted(
        output({"category": "bug", "priority": 3, "summary": "Crashes at login."}),
        output({"category": "bug", "priority": 1, "summary": "Crashes at login."}),
    )
    async with harness_for_test(SPEC, model=model) as harness:
        result = await harness.run("triage", Ticket(text="It crashes at login."))
    assert result.ok
    assert len(model.requests) == 2
    assert_trace(result, step("output.before", source="validation.rules[bugs-are-urgent]"))


async def test_emails_never_reach_the_model() -> None:
    model = scripted(output(BILLING))
    async with harness_for_test(SPEC, model=model) as harness:
        result = await harness.run("triage", Ticket(text="Refund me. ann@example.com"))
    assert_no_content([model.requests, result], "ann@example.com")


async def test_refunds_over_the_cap_are_blocked() -> None:
    model = scripted(tool_call("refund_payment", order_id="A-1001", amount_usd=900))
    async with harness_for_test(SPEC, model=model) as harness:
        result = await harness.run("orders", "Refund $900 on order A-1001.", principal="ann")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "policy_denied"


async def test_big_refunds_wait_for_finance() -> None:
    model = scripted(tool_call("refund_payment", order_id="A-1001", amount_usd=250))
    async with harness_for_test(SPEC, model=model) as harness:
        result = await harness.run("orders", "Refund $250 on order A-1001.", principal="ann")
    assert result.status is hw.RunStatus.AWAITING_APPROVAL
    assert result.approval is not None
    assert result.approval.approver_role == "finance"
