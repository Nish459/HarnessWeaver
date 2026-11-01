"""The harness checks every task's final output, whichever runner made it (R1, R4)."""

from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw

from .conftest import Builder, scripted, spec
from .direct_support import hooks_fired
from .l1_support import org_profile

pytestmark = pytest.mark.anyio

KEY = "AKIAIOSFODNN7EXAMPLE"  # AWS's documented example key
SECRETS: dict[str, Any] = {"output": [{"id": "keys", "use": "secrets.scan", "action": "block"}]}
SESSION = {"runner": {"use": "session", "handler": "hw_testkit:returns_a_key"}}
WORKFLOW = {
    "runner": {
        "use": "workflow",
        "steps": [
            {"id": "fetch", "handler": "hw_testkit:fetches_a_key"},
            {"id": "report", "handler": "hw_testkit:reports_the_key", "needs": ["fetch"]},
        ],
    }
}


def blocked_by_guard(result: hw.RunResult) -> bool:
    return (
        result.status is hw.RunStatus.BLOCKED
        and result.output is None
        and result.error is not None
        and result.error.details["code"] == "guard_blocked"
    )


async def test_a_session_handlers_return_value_is_checked(build: Builder) -> None:
    result = await build(spec(guardrails=SECRETS, tasks={"t": SESSION})).run("t", "hi")
    assert blocked_by_guard(result)
    assert hooks_fired(result).count("output.before") == 1


async def test_a_workflows_output_is_checked_by_its_profiles_guard(build: Builder) -> None:
    harness = build(spec(extends=["profile://workflow@^1"], tasks={"t": WORKFLOW}))
    assert blocked_by_guard(await harness.run("t", "hi"))


async def test_a_custom_runners_return_value_is_checked(build: Builder) -> None:
    harness = build(spec(guardrails=SECRETS, tasks={"t": {"runner": {"use": "testkit.partial"}}}))
    assert blocked_by_guard(await harness.run("t", f"key {KEY}"))


@pytest.mark.parametrize("task", [SESSION, WORKFLOW], ids=["session", "workflow"])
async def test_a_locked_baseline_guard_holds(build: Builder, tmp_path: Path, task: Any) -> None:
    baseline = org_profile(tmp_path, guardrails=SECRETS, locks=["guardrails.output[keys]"])
    harness = build(spec(extends=[f"{baseline}@^1"], tasks={"t": task}))
    assert blocked_by_guard(await harness.run("t", "hi"))


async def test_a_redaction_replaces_the_returned_value(build: Builder) -> None:
    guards = {"output": [{"id": "keys", "use": "secrets.scan", "action": "redact"}]}
    result = await build(spec(guardrails=guards, tasks={"t": SESSION})).run("t", "hi")
    assert result.ok
    assert result.output == "key [SECRET]"


async def test_a_repair_request_follows_on_failure(build: Builder) -> None:
    guards = {"output": [{"id": "keys", "use": "secrets.scan", "action": "repair"}]}
    harness = build(
        spec(guardrails=guards, validation={"on_failure": "escalate"}, tasks={"t": SESSION})
    )
    result = await harness.run("t", "hi")
    assert result.status is hw.RunStatus.ESCALATED
    assert result.error is not None
    assert result.error.details["code"] == "validation_failed"
    assert result.output is None


@pytest.mark.parametrize("task", [SESSION, WORKFLOW], ids=["session", "workflow"])
async def test_an_approved_output_completes_on_resume(build: Builder, task: Any) -> None:
    guards = {"output": [{"id": "keys", "use": "secrets.scan", "action": "require_approval"}]}
    harness = build(spec(guardrails=guards, tasks={"t": task}))
    first = await harness.run("t", "hi")
    assert first.status is hw.RunStatus.AWAITING_APPROVAL
    assert first.approval is not None
    result = await harness.approve(first.run_id, first.approval.approval_id, approver="bob")
    assert result.ok
    assert result.output == f"key {KEY}"


async def test_a_direct_run_checks_its_answer_once(build: Builder) -> None:
    harness = build(spec(models=scripted({"text": "fine"}), tasks={"t": {"runner": "direct"}}))
    result = await harness.run("t", "hi")
    assert result.ok
    assert hooks_fired(result).count("output.before") == 1


async def test_a_value_the_handler_validated_isnt_checked_twice(build: Builder) -> None:
    task = {"runner": {"use": "session", "handler": "hw_testkit:validates_its_answer"}}
    result = await build(spec(guardrails=SECRETS, tasks={"t": task})).run("t", "fine")
    assert result.output == "fine"
    assert hooks_fired(result).count("output.before") == 1


async def test_a_value_changed_after_validation_is_checked(build: Builder) -> None:
    task = {"runner": {"use": "session", "handler": "hw_testkit:changes_after_validating"}}
    result = await build(spec(guardrails=SECRETS, tasks={"t": task})).run("t", "fine")
    assert blocked_by_guard(result)
    assert hooks_fired(result).count("output.before") == 2
