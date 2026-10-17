"""The workflow runner: DAG order, parallel steps, evaluator-optimizer loops, resume."""

from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.errors import SpecError

from .conftest import Builder, scripted, spec

pytestmark = pytest.mark.anyio

STEPS = [
    {"id": "extract", "handler": "hw_testkit:extract"},
    {"id": "classify", "handler": "hw_testkit:classify", "needs": ["extract"]},
    {"id": "summarize", "handler": "hw_testkit:summarize", "needs": ["extract"]},
    {
        "id": "report",
        "handler": "hw_testkit:draft",
        "needs": ["classify", "summarize"],
        "evaluator": "hw_testkit:review",
        "max_rounds": 3,
    },
]


def workflow(steps: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"runner": {"use": "workflow", "steps": steps, **extra}}


async def test_steps_run_in_graph_order_with_a_review_loop(build: Builder, testkit: Any) -> None:
    harness = build(
        spec(models=scripted({"text": "short summary"}), tasks={"flow": workflow(STEPS)})
    )
    result = await harness.run("flow", "please refund")
    assert result.ok
    assert result.output == "draft 2 for billing"
    names = [note[0] for note in testkit.RECORDER.notes]
    assert names[0] == "extract"
    assert set(names[1:3]) == {"classify", "summarize"}
    assert names[3:] == ["draft", "review", "draft", "review", "draft", "review"]
    drafts = [n for n in testkit.RECORDER.notes if n[0] == "draft"]
    assert drafts == [
        ("draft", 0, None),
        ("draft", 1, "make it better"),
        ("draft", 2, "make it better"),
    ]
    verdicts = [e.reason for e in result.trace if e.source == "workflow.report"]
    assert verdicts == ["rejected", "rejected", "accepted"]


@pytest.mark.parametrize(
    ("on_reject", "status"),
    [("escalate", "escalated"), ("block", "blocked"), ("accept", "completed")],
)
async def test_a_step_the_evaluator_never_accepts(
    build: Builder, on_reject: str, status: str
) -> None:
    steps = [
        {"id": "a", "handler": "hw_testkit:extract"},
        {
            "id": "b",
            "handler": "hw_testkit:draft",
            "needs": ["a"],
            "evaluator": "hw_testkit:never_happy",
            "max_rounds": 2,
            "on_reject": on_reject,
        },
    ]
    steps[1]["handler"] = "hw_testkit:extract"
    harness = build(
        spec(models=scripted({"text": "x"}), tasks={"flow": workflow(steps, output="b")})
    )
    result = await harness.run("flow", "x")
    assert result.status == status


async def test_after_approval_only_the_interrupted_step_runs_again(
    build: Builder, testkit: Any
) -> None:
    steps = [
        {"id": "extract", "handler": "hw_testkit:extract"},
        {"id": "classify", "handler": "hw_testkit:classify", "needs": ["extract"]},
        {"id": "refund", "handler": "hw_testkit:approve_refund", "needs": ["classify"]},
    ]
    harness = build(
        spec(
            models=scripted({"text": "x"}),
            middleware=[
                {
                    "use": "testkit.script",
                    "rules": [{"hook": "tool.before", "outcome": "suspend", "tool": "refund"}],
                }
            ],
            tasks={"flow": workflow(steps)},
        )
    )
    first = await harness.run("flow", "refund it")
    assert first.status is hw.RunStatus.AWAITING_APPROVAL
    assert first.approval is not None
    result = await harness.approve(first.run_id, first.approval.approval_id, approver="x")
    assert result.ok
    assert result.output == {"refunded": 5}
    names = [note[0] for note in testkit.RECORDER.notes]
    assert names == ["extract", "classify", "approve_refund", "approve_refund"]


async def test_a_suspended_parallel_step_wins_over_its_siblings(build: Builder) -> None:
    steps = [
        {"id": "extract", "handler": "hw_testkit:extract"},
        {"id": "classify", "handler": "hw_testkit:classify", "needs": ["extract"]},
        {"id": "refund", "handler": "hw_testkit:approve_refund", "needs": ["classify"]},
        {"id": "summary", "handler": "hw_testkit:summarize", "needs": ["classify"]},
    ]
    harness = build(
        spec(
            models=scripted({"wait": True}),
            middleware=[
                {
                    "use": "testkit.script",
                    "rules": [{"hook": "tool.before", "outcome": "suspend", "tool": "refund"}],
                }
            ],
            tasks={"flow": workflow(steps, output="refund")},
        )
    )
    first = await harness.run("flow", "refund it")
    assert first.status is hw.RunStatus.AWAITING_APPROVAL


async def test_a_failing_step_fails_the_run(build: Builder) -> None:
    steps = [
        {"id": "a", "handler": "hw_testkit:extract"},
        {"id": "b", "handler": "hw_testkit:explode", "needs": ["a"]},
        {"id": "c", "handler": "hw_testkit:extract", "needs": ["a"]},
    ]
    harness = build(spec(models=scripted({"text": "x"}), tasks={"flow": workflow(steps)}))
    result = await harness.run("flow", "x")
    assert result.status is hw.RunStatus.FAILED
    assert result.error is not None
    assert result.error.code is hw.errors.ErrorCode.INTERNAL


@pytest.mark.parametrize(
    ("steps", "extra", "message"),
    [
        ([{"id": "a", "handler": "hw_testkit:extract"}] * 2, {}, "unique"),
        ([{"id": "a", "handler": "hw_testkit:extract", "needs": ["z"]}], {}, "unknown step"),
        (
            [
                {"id": "a", "handler": "hw_testkit:extract", "needs": ["b"]},
                {"id": "b", "handler": "hw_testkit:extract", "needs": ["a"]},
            ],
            {},
            "cycle",
        ),
        ([{"id": "a", "handler": "hw_testkit:extract"}], {"output": "z"}, "not a step"),
        ([{"id": "a", "handler": "hw_testkit:missing"}], {}, "can't import"),
        ([{"id": "a", "handler": "no_colon"}], {}, "must look like"),
    ],
)
def test_invalid_workflows_fail_to_load(
    build: Builder, steps: list[dict[str, Any]], extra: dict[str, Any], message: str
) -> None:
    with pytest.raises(SpecError, match=message):
        build(spec(models=scripted({"text": "x"}), tasks={"flow": workflow(steps, **extra)}))
