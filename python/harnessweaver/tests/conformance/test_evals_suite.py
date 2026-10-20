"""Runner for the ``evals`` fixtures: graders, datasets, baselines, sampling, shadow reports."""

from typing import Any

import pytest

from harnessweaver.core.errors import SpecError, UnknownProvider
from harnessweaver.core.evals import (
    Baseline,
    CaseResult,
    EvalSample,
    GraderResult,
    GuardFiring,
    parse_graders,
)
from harnessweaver.core.registry import PluginCatalog, Registry
from harnessweaver.core.runs import RunStatus
from harnessweaver.modules.evals import (
    build_grader,
    compare,
    read_dataset,
    sampled,
    shadow_report,
    summarize,
)

pytestmark = [pytest.mark.conformance_suite("evals"), pytest.mark.anyio]

REGISTRY = Registry(PluginCatalog.default())


async def _grade(case: dict[str, Any]) -> None:
    expect = case["expect"]
    try:
        (spec,) = parse_graders([case["grader"]])
        grader = build_grader(REGISTRY, spec)
    except UnknownProvider:
        assert expect == {"error": "unknown"}
        return
    except SpecError:
        assert expect == {"error": "invalid"}
        return
    assert "error" not in expect, "the grader should have been refused"
    grade = await grader.grade(EvalSample.model_validate(case["sample"]))
    assert grade.passed is expect["passed"]
    assert grade.score == (1.0 if expect["passed"] else 0.0)


def _dataset(case: dict[str, Any]) -> None:
    expect = case["expect"]
    try:
        dataset = read_dataset(case["dataset"], case["name"])
    except SpecError:
        assert expect == {"error": "invalid"}
        return
    assert "error" not in expect, "the dataset should have been refused"
    labels = {c.id: [g.label for g in dataset.graders_for(c)] for c in dataset.cases}
    assert labels == expect["cases"]


def _summary(case: dict[str, Any]) -> None:
    spec = case["summarize"]
    cases = [
        CaseResult(
            id=c["id"],
            passed=all(g["passed"] for g in c["grades"]),
            status=RunStatus.COMPLETED,
            grades=tuple(
                GraderResult(grader=g["grader"], passed=g["passed"], score=float(g["passed"]))
                for g in c["grades"]
            ),
        )
        for c in spec["cases"]
    ]
    result = summarize("s", "t", spec["threshold"], cases)
    assert {
        "pass_rate": result.pass_rate,
        "passed": result.passed,
        "grader_rates": result.grader_rates,
    } == case["expect"]


def _shadow(case: dict[str, Any]) -> None:
    cases = [
        (
            c["id"],
            parse_graders(c["graders"]),
            [GuardFiring.model_validate(f) for f in c["guards"]],
        )
        for c in case["cases"]
    ]
    report = shadow_report(case["shadow_guards"], cases)
    shown = [r.model_dump(mode="json") for r in report]
    assert shown == case["expect"]["report"]


async def test_evals(case: dict[str, Any]) -> None:
    if "grader" in case:
        await _grade(case)
    elif "dataset" in case:
        _dataset(case)
    elif "summarize" in case:
        _summary(case)
    elif "current" in case:
        baseline = case["baseline"]
        found = compare(
            Baseline.model_validate(baseline) if baseline is not None else None,
            case["current"]["cases"],
        )
        shown = {**found.model_dump(mode="json"), "regression": found.regression}
        assert shown == case["expect"]
    elif "run_id" in case:
        assert sampled(case["run_id"], case["rate"]) is case["expect"]["sampled"]
    else:
        _shadow(case)
