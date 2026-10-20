"""Guardrails in a running harness: redaction, blocking, bands, shadow mode, groups, the judge."""

from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.trace import TraceKind
from harnessweaver.errors import ProviderError, SpecError

from .conftest import Builder, spec
from .l1_support import SUMMARY, org_profile, scripted, scripted_model_of

pytestmark = pytest.mark.anyio


async def test_an_extraction_task_repairs_once_then_escalates(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            extends=["profile://extraction"],
            models=scripted({"output": {"title": "Q3"}}),
            tasks={"summarize": {"runner": "direct", "output": SUMMARY}},
        )
    )
    result = await harness.run("summarize", "summary for alice@example.com")
    assert result.status is hw.RunStatus.ESCALATED
    assert result.error is not None
    assert result.error.details["code"] == "validation_failed"
    model = harness.registry.provider("ModelProvider", "scripted")
    assert model.name == "scripted"
    chain = harness.hooks("summarize")
    assert [(r.name, r.band) for r in chain[hw.HookPoint.INPUT_BEFORE]] == [
        ("guardrails.input[extraction-pii]", hw.Band.PLATFORM)
    ]


async def test_guards_redact_input_and_block_secret_output(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(
            extends=["profile://extraction"],
            models=scripted({"output": {"title": "key AKIAIOSFODNN7EXAMPLE", "words": 2}}),
            tasks={"summarize": {"runner": "direct", "output": SUMMARY}},
        )
    )
    result = await harness.run("summarize", "summary for alice@example.com")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "guard_blocked"
    scripted_model = scripted_model_of(harness)
    assert scripted_model.requests[0].messages[-1].content == "summary for [EMAIL]"
    assert "AKIA" not in result.model_dump_json()  # R9: reasons and findings only


async def test_guard_bands_follow_the_layer_that_declared_them(
    build: Builder, tmp_path: Path
) -> None:
    ref = org_profile(
        tmp_path, guardrails={"output": [{"id": "org-secrets", "use": "secrets.scan"}]}
    )
    harness = build(
        spec(
            extends=[ref, "profile://extraction"],
            models=scripted({"text": "x"}),
            guardrails={
                "output": [{"id": "app-topics", "use": "topic.deny", "topics": {"t": ["x"]}}]
            },
            tasks={
                "t": {
                    "runner": "direct",
                    "guardrails": {
                        "output": [{"id": "task-size", "use": "size.limit", "max_chars": 9}]
                    },
                }
            },
        )
    )
    chain = harness.hooks("t")[hw.HookPoint.OUTPUT_BEFORE]
    assert [(r.name, r.band) for r in chain] == [
        ("guardrails.output[org-secrets]", hw.Band.BASELINE),
        ("guardrails.output[extraction-secrets]", hw.Band.PLATFORM),
        ("guardrails.output[app-topics]", hw.Band.APP),
        ("tasks.t.guardrails.output[task-size]", hw.Band.TASK),
    ]
    assert [r.name for r in harness.hooks("other")[hw.HookPoint.OUTPUT_BEFORE]][-1] != (
        "tasks.t.guardrails.output[task-size]"
    )


async def test_a_shadow_guard_is_traced_but_does_not_act(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "your key is AKIAIOSFODNN7EXAMPLE"}),
            guardrails={"output": [{"id": "keys", "use": "secrets.scan", "mode": "log_only"}]},
            tasks={"t": {"runner": "direct"}},
        )
    )
    result = await harness.run("t", "q")
    assert result.ok
    shadow = [
        e
        for e in result.trace
        if e.kind is TraceKind.OUTCOME and (e.reason or "").startswith("would block")
    ]
    assert len(shadow) == 1
    assert shadow[0].source == "guardrails.output[keys]"


BILLING = {"id": "billing", "use": "regex.deny", "patterns": ["billing"]}


async def test_an_approved_output_passes_the_guard_that_asked(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "billing for alice@example.com"}),
            guardrails={
                "output": [
                    {"id": "pii", "use": "pii.regex"},
                    {**BILLING, "action": "require_approval"},
                ]
            },
            tasks={"t": {"runner": "direct"}},
        )
    )
    first = await harness.run("t", "q")
    assert first.status is hw.RunStatus.AWAITING_APPROVAL
    assert first.approval is not None
    result = await harness.approve(first.run_id, first.approval.approval_id, approver="bob")
    assert result.status is hw.RunStatus.COMPLETED
    assert result.output == "billing for [EMAIL]"  # the approval doesn't undo a redaction
    approved = [e for e in result.trace if e.code == "guard_approved"]
    assert len(approved) == 1
    assert approved[0].details == {
        "guard": "guardrails.output[billing]",
        "action": "require_approval",
        "approved_by": "bob",
        "findings": ["regex:0"],
    }
    outcome = [
        e
        for e in result.trace
        if e.kind is TraceKind.OUTCOME and e.source == "guardrails.output[billing]"
    ]
    assert outcome[-1].reason == "guardrails.output[billing]: approved by bob"


async def test_an_approval_answers_only_the_approval(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "billing refund"}),
            guardrails={
                "output": [
                    {**BILLING, "action": "require_approval"},
                    {
                        "id": "refunds",
                        "use": "regex.deny",
                        "patterns": ["refund"],
                        "action": "escalate",
                    },
                ]
            },
            tasks={"t": {"runner": "direct"}},
        )
    )
    first = await harness.run("t", "q")
    assert first.status is hw.RunStatus.AWAITING_APPROVAL  # Suspend outranks Escalate
    assert first.approval is not None
    result = await harness.approve(first.run_id, first.approval.approval_id, approver="bob")
    assert result.status is hw.RunStatus.ESCALATED


async def test_guard_configuration_errors(build: Builder) -> None:
    with pytest.raises(SpecError, match="stage"):
        build(
            spec(
                models=scripted({"text": "x"}),
                guardrails={"tool_result": [{"use": "llm.judge", "criteria": "c"}]},
            )
        )
    with pytest.raises(SpecError, match="sidecar"):
        build(
            spec(
                models=scripted({"text": "x"}),
                guardrails={"input": [{"use": "pii.regex", "where": "sidecar"}]},
            )
        )
    with pytest.raises(SpecError, match="max_chars or max_bytes"):
        build(spec(models=scripted({"text": "x"}), guardrails={"input": [{"use": "size.limit"}]}))
    with pytest.raises(SpecError, match="invalid pattern"):
        build(
            spec(
                models=scripted({"text": "x"}),
                guardrails={"input": [{"use": "regex.deny", "patterns": ["("]}]},
            )
        )
    with pytest.raises(SpecError, match="unknown secret kinds"):
        build(
            spec(
                models=scripted({"text": "x"}),
                guardrails={"input": [{"use": "secrets.scan", "kinds": ["x"]}]},
            )
        )


async def test_a_baseline_guard_must_fail_closed(build: Builder, tmp_path: Path) -> None:
    ref = org_profile(
        tmp_path, guardrails={"input": [{"id": "pii", "use": "pii.regex", "fail_mode": "open"}]}
    )
    with pytest.raises(SpecError, match="R2"):
        build(spec(models=scripted({"text": "x"}), extends=[ref]))


async def test_parallel_guards_and_member_failures(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            guardrails={
                "input": [
                    {"id": "inj", "use": "injection.heuristic", "parallel": True},
                    {
                        "id": "judge",
                        "use": "llm.judge",
                        "criteria": "be nice",
                        "parallel": True,
                        "fail_mode": "open",
                        "timeout": "1s",
                    },
                    {"id": "pii", "use": "pii.regex", "parallel": True, "mode": "log_only"},
                ]
            },
            tasks={"t": {"runner": "direct"}},
        )
    )
    (group,) = harness.hooks("t")[hw.HookPoint.INPUT_BEFORE]
    assert group.name == "guardrails.input[inj+judge+pii]"
    result = await harness.run("t", "hello bob@example.com")
    # The judge got the scripted "x", which isn't JSON: it fails open; pii is shadow only.
    assert result.ok
    reasons = [e.reason or "" for e in result.trace]
    assert any("guard failed (ProviderError)" in r for r in reasons)
    assert any("would redact: pii" in r for r in reasons)


async def test_the_llm_judge(build: Builder) -> None:
    harness = build(
        spec(
            models={
                "provider": "scripted",
                "rules": [
                    {
                        "contains": "rude",
                        "reply": {"output": {"pass": False, "reason": "rude words"}},
                    },
                    {"role": "user", "contains": "polite", "reply": {"output": {"pass": True}}},
                ],
                "replies": [{"text": "a polite answer"}],
            },
            guardrails={"output": [{"id": "judge", "use": "llm.judge", "criteria": "no rudeness"}]},
            tasks={"t": {"runner": "direct"}},
        )
    )
    assert (await harness.run("t", "q")).ok
    rude = build(
        spec(
            models={
                "provider": "scripted",
                "rules": [
                    {
                        "role": "user",
                        "contains": "rude",
                        "reply": {"output": {"pass": False, "reason": "quote"}},
                    }
                ],
                "replies": [{"text": "a rude answer"}],
            },
            guardrails={"output": [{"id": "judge", "use": "llm.judge", "criteria": "no rudeness"}]},
            tasks={"t": {"runner": "direct"}},
        )
    )
    result = await rude.run("t", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert "quote" not in result.model_dump_json()  # the judge's words aren't kept (R9)


async def test_the_judge_needs_a_run_and_json() -> None:
    from harnessweaver.modules.guardrails import LlmJudge
    from harnessweaver.modules.guardrails.providers import JudgeConfig

    judge = LlmJudge(JudgeConfig(criteria="c"))
    with pytest.raises(ProviderError, match="active run"):
        await judge.check("x", hw.Envelope.new(tenant="t", principal="p"))
