"""Harness.authorize: the governor's verdict on a call, as a dry run (``policy test``)."""

from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.errors import NotFound

from .conftest import Builder
from .governance_support import call, manifest, refund_tool, tool_spec

pytestmark = pytest.mark.anyio


def governed(build: Builder, tmp_path: Path, *replies: dict[str, Any]) -> hw.Harness:
    refund_tool(
        tmp_path,
        approval={"when": "args.amount_usd > 100", "approver_role": "finance"},
        rate_limit={"per_principal": "1/m"},
    )
    rules = [{"id": "no-globex", "when": "tenant == 'globex'", "effect": "deny"}]
    document = tool_spec(
        *(replies or ({"text": "x"},)),
        tools=["refund_payment"],
        policy={"rules": rules},
        tasks={
            "t": {"runner": "direct", "tools": ["refund_payment"]},
            "careful": {"runner": "direct", "approvals": {"tools": ["refund_payment"]}},
        },
    )
    return build(document, tools=None)


@pytest.mark.parametrize(
    ("args", "who", "decision", "step", "code"),
    [
        ({"amount_usd": 5}, {}, "allow", 7, None),
        ({"amount_usd": 500}, {}, "require_approval", 7, "approval_required"),
        ({"amount_usd": 5}, {"tenant": "globex"}, "block", 3, "policy_denied"),
        ({"amount_usd": -1}, {}, "block", 2, "schema_invalid"),
        ({"amount_usd": 5}, {"task": "careful"}, "require_approval", 7, "approval_required"),
    ],
)
async def test_the_verdict_of_one_call(
    build: Builder,
    tmp_path: Path,
    testkit: Any,
    args: dict[str, Any],
    who: dict[str, Any],
    decision: str,
    step: int,
    code: str | None,
) -> None:
    app = governed(build, tmp_path)
    verdict = await app.authorize("refund_payment", args, principal="alice", **who)
    assert (verdict.decision, verdict.step, verdict.code) == (decision, step, code)
    assert testkit.RECORDER.handled == []  # nothing ran
    if args["amount_usd"] == 500:
        assert verdict.approver_role == "finance"


@pytest.mark.parametrize(
    ("manifest_role", "task_role", "role"),
    [
        (None, None, "finance"),  # the spec's approvals.approver_role
        (None, "support-lead", "support-lead"),  # the task's approvals
        ("cfo", "support-lead", "cfo"),  # the manifest, the step that asked
    ],
)
async def test_the_approver_role_is_the_one_a_real_run_waits_for(
    build: Builder,
    tmp_path: Path,
    testkit: Any,
    manifest_role: str | None,
    task_role: str | None,
    role: str,
) -> None:
    refund_tool(tmp_path, approval={"approver_role": manifest_role} if manifest_role else None)
    rules = [{"when": "args.amount_usd > 100", "effect": "require_approval"}]
    document = tool_spec(
        call("refund_payment", amount_usd=500),
        tools=["refund_payment"],
        policy={"rules": rules},
        approvals={"approver_role": "finance"},
        task={"approvals": {"approver_role": task_role}},
    )
    app = build(document, tools=None)
    verdict = await app.authorize("refund_payment", {"amount_usd": 500}, task="t")
    waiting = await app.run("t", "refund order 7")
    assert waiting.approval is not None
    assert (verdict.approver_role, waiting.approval.approver_role) == (role, role)


async def test_a_dry_run_uses_up_no_rate_limit(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    app = governed(build, tmp_path, call("refund_payment", amount_usd=5), {"text": "done"})
    for _ in range(3):
        verdict = await app.authorize("refund_payment", {"amount_usd": 5}, principal="alice")
        assert verdict.decision == "allow"
    result = await app.run("t", "refund", principal="alice")
    assert result.ok, result.error
    assert len(testkit.RECORDER.handled) == 1


async def test_labels_drive_the_trifecta(build: Builder, tmp_path: Path, testkit: Any) -> None:
    manifest(
        tmp_path,
        "send_email",
        handler="hw_testkit:send_email",
        side_effect="write_external",
        egress=["smtp.example.com"],
    )
    app = build(tool_spec({"text": "x"}, tools=["send_email"]), tools=None)
    tainted = hw.Labels(untrusted_seen=True, private_seen=True)
    clean = await app.authorize("send_email", {"to": "a@example.com", "body": "hi"})
    risky = await app.authorize("send_email", {"to": "a@example.com", "body": "hi"}, labels=tainted)
    assert (clean.decision, risky.decision) == ("allow", "require_approval")
    assert "lethal trifecta" in risky.reason


async def test_unknown_tools_and_tasks(build: Builder, tmp_path: Path, testkit: Any) -> None:
    app = governed(build, tmp_path)
    verdict = await app.authorize("wire_money", {})
    assert (verdict.decision, verdict.step, verdict.code) == ("block", 1, "tool_unknown")
    with pytest.raises(NotFound, match="unknown task"):
        await app.authorize("refund_payment", {"amount_usd": 5}, task="nope")
