"""Validation rules (cel-lite) ask for repairs, and fail closed when they can't be checked."""

from pathlib import Path

import pytest

import harnessweaver as hw

from .conftest import Builder, spec
from .l1_support import SUMMARY, org_profile, scripted, scripted_model_of

pytestmark = pytest.mark.anyio


async def test_validation_rules_ask_for_repairs(build: Builder, tmp_path: Path) -> None:
    ref = org_profile(
        tmp_path,
        validation={
            "rules": [
                {"id": "positive", "when": "output.words <= 0", "message": "words must be positive"}
            ]
        },
    )
    harness = build(
        spec(
            extends=[ref],
            models=scripted(
                {"output": {"title": "T", "words": 0}}, {"output": {"title": "T", "words": 3}}
            ),
            validation={
                "rules": [
                    {"id": "title", "when": "size(output.title) == 0", "message": "needs a title"}
                ]
            },
            tasks={"t": {"runner": "direct", "output": SUMMARY}},
        )
    )
    (org, app) = harness.hooks("t")[hw.HookPoint.OUTPUT_BEFORE]
    assert (org.name, org.band) == ("validation.rules[positive]", hw.Band.BASELINE)
    assert (app.name, app.band) == ("validation.rules[title]", hw.Band.APP)
    result = await harness.run("t", "q")
    assert result.output == {"title": "T", "words": 3}
    assert "words must be positive" in scripted_model_of(harness).requests[1].messages[-1].content


async def test_a_rule_that_cannot_be_evaluated_counts_as_broken(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "plain"}),
            validation={
                "max_repairs": 0,
                "rules": [{"when": "output.total < 0", "message": "bad total"}],
            },
            tasks={"t": {"runner": "direct"}},
        )
    )
    result = await harness.run("t", "q")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert "couldn't be checked" in result.error.message
