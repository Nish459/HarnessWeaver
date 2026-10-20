"""__app_name__ tests: offline, with no network and no keys (RULES R14)."""

from pathlib import Path

import pytest

import harnessweaver as hw
from harnessweaver.testing import harness_for_test, scripted

pytestmark = pytest.mark.anyio

SPEC = Path(__file__).resolve().parents[1] / "harness.yaml"


async def test_the_golden_set_passes_offline() -> None:
    result = await hw.load(SPEC, env="offline").evaluate("evals/golden.yaml")
    assert result.passed, [case.id for case in result.cases if not case.passed]


async def test_the_reviewer_sends_the_first_draft_back() -> None:
    result = await hw.load(SPEC, env="offline").run("triage", "Charged twice for Pro.")
    assert result.ok, result.error
    assert result.output["category"] == "billing"
    assert "billing" in result.output["reply"].lower()
    reviews = [e.reason for e in result.trace if e.source == "workflow.reply"]
    assert reviews == ["rejected", "accepted"]  # the first draft came back with feedback


async def test_a_reply_the_reviewer_never_accepts_escalates() -> None:
    model = scripted("billing", "A summary.", "Thanks for writing.", repeat_last=True)
    result = await harness_for_test(SPEC, model=model).run("triage", "Charged twice.")
    assert result.status is hw.RunStatus.ESCALATED
