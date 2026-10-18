"""__app_name__ tests: offline, with no network and no keys (RULES R14)."""

from pathlib import Path

import pytest
from app.models import Message, TicketSummary

import harnessweaver as hw
from harnessweaver.testing import assert_trace, harness_for_test, output, scripted

pytestmark = pytest.mark.anyio

SPEC = Path(__file__).resolve().parents[1] / "harness.yaml"
VALID = {
    "category": "billing",
    "priority": 2,
    "product": "Pro plan",
    "summary": "Charged twice; wants a refund.",
}


async def test_the_offline_overlay_extracts_a_summary() -> None:
    harness = hw.load(SPEC, env="offline")
    result = await harness.run("extract", Message(text="I was charged twice."))
    assert result.ok
    assert TicketSummary.model_validate(result.output).category == "billing"


async def test_an_invalid_answer_is_repaired_once() -> None:
    model = scripted(output({"category": "billing"}), output(VALID))
    result = await harness_for_test(SPEC, model=model).run(
        "extract", Message(text="Refund please.")
    )
    assert result.ok
    assert len(model.requests) == 2
    assert_trace(result, "model.after", "model.after", "output.before", "run.end")


async def test_a_second_invalid_answer_escalates() -> None:
    model = scripted(output({"category": "billing"}))
    result = await harness_for_test(SPEC, model=model).run(
        "extract", Message(text="Refund please.")
    )
    assert result.status is hw.RunStatus.ESCALATED


async def test_customer_emails_never_reach_the_model() -> None:
    model = scripted(output(VALID))
    harness = harness_for_test(SPEC, model=model)
    await harness.run("extract", Message(text="Refund please. ann@example.com"))
    assert "ann@example.com" not in model.requests[0].messages[-1].content
