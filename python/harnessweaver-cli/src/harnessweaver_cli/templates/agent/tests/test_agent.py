"""__app_name__ tests: offline, with no network and no keys (RULES R14)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from app import tools

import harnessweaver as hw

pytestmark = pytest.mark.anyio

SPEC = Path(__file__).resolve().parents[1] / "harness.yaml"
LEAD = hw.Principal(id="lee", roles=("support-lead",))


@pytest.fixture(autouse=True)
def no_refunds() -> Iterator[None]:
    tools.REFUNDS.clear()
    yield
    tools.REFUNDS.clear()


async def test_the_red_team_set_passes_offline() -> None:
    result = await hw.load(SPEC, env="offline").evaluate("evals/redteam.yaml")
    assert result.passed, [case.id for case in result.cases if not case.passed]
    assert tools.REFUNDS == []  # nothing in the red-team set moved money


async def test_a_lookup_completes() -> None:
    result = await hw.load(SPEC, env="offline").run("support", "Where is my order A-1001?")
    assert result.ok, result.error
    assert result.output == "Your order has shipped and arrives soon."


async def test_a_refund_waits_for_a_support_lead() -> None:
    harness = hw.load(SPEC, env="offline")
    waiting = await harness.run("support", "Please refund order A-1001, it never arrived.")
    assert waiting.status is hw.RunStatus.AWAITING_APPROVAL
    assert waiting.approval is not None
    assert waiting.approval.approver_role == "support-lead"
    assert tools.REFUNDS == []
    done = await harness.approve(waiting.run_id, waiting.approval.approval_id, approver=LEAD)
    assert done.ok, done.error
    assert done.output == "Your refund is on its way."
    assert [r["amount_usd"] for r in tools.REFUNDS] == [120]


async def test_only_a_support_lead_may_approve() -> None:
    harness = hw.load(SPEC, env="offline")
    waiting = await harness.run("support", "Please refund order A-1001.")
    assert waiting.approval is not None
    with pytest.raises(hw.errors.HarnessError):
        await harness.approve(waiting.run_id, waiting.approval.approval_id, approver="mallory")
