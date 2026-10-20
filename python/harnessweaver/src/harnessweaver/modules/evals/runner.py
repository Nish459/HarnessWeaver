"""Running an eval suite: each case's task, graded (DESIGNS No. 23)."""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from pydantic import JsonValue

from harnessweaver.core.envelope import Principal
from harnessweaver.core.evals import (
    CaseResult,
    EvalCase,
    EvalDataset,
    EvalSample,
    GraderResult,
    GraderSpec,
    ShadowGuardReport,
    SuiteResult,
)
from harnessweaver.core.ports import Evaluator
from harnessweaver.core.registry import Registry
from harnessweaver.core.results import RunResult
from harnessweaver.modules.evals.datasets import build_graders
from harnessweaver.modules.evals.results import firings, shadow_report, summarize
from harnessweaver.modules.guardrails import configured_guards
from harnessweaver.spec.models import HarnessSpec

__all__ = ["EVAL_PRINCIPAL", "EvalTarget", "run_suite", "shadow_guards", "suite_shadow_report"]

EVAL_PRINCIPAL = "harnessweaver.evals"
"""Who judges' sessions run as."""


class EvalTarget(Protocol):
    """What running a suite needs from a harness."""

    @property
    def registry(self) -> Registry: ...

    def output_schema(self, task: str) -> dict[str, JsonValue] | None: ...

    async def run(
        self, task: str, input: Any = None, *, principal: Principal | str = ..., tenant: str = ...
    ) -> RunResult: ...

    def session(
        self, task: str | None = None, *, principal: Principal | str = ..., tenant: str = ...
    ) -> AbstractAsyncContextManager[Any]: ...


async def _grade(
    graders: Sequence[tuple[GraderSpec, Evaluator]], sample: EvalSample
) -> list[GraderResult]:
    found: list[GraderResult] = []
    for spec, grader in graders:
        try:
            grade = await grader.grade(sample)
        except Exception as exc:  # one broken grader fails its case, not the suite
            found.append(
                GraderResult(
                    grader=spec.label,
                    passed=False,
                    score=0.0,
                    reason=f"the grader failed ({type(exc).__name__})",
                )
            )
            continue
        found.append(GraderResult(grader=spec.label, **grade.model_dump()))
    return found


async def _case(
    target: EvalTarget, dataset: EvalDataset, case: EvalCase, schema: dict[str, JsonValue] | None
) -> CaseResult:
    specs = dataset.graders_for(case)
    graders = build_graders(target.registry, specs)
    result = await target.run(
        dataset.task, case.input, principal=case.principal, tenant=case.tenant
    )
    guards = firings(result.trace)
    sample = EvalSample(
        case=case.id,
        task=dataset.task,
        input=case.input,
        expect=case.expect,
        output=result.output,
        status=result.status,
        error_code=result.error.code if result.error is not None else None,
        guards=guards,
        output_schema=schema,
    )
    if all(target.registry.provider("Evaluator", s.use).deterministic for s in specs):
        grades = await _grade(graders, sample)
    else:
        # Judges call models: in a session, so the calls are governed and budgeted.
        async with target.session(principal=EVAL_PRINCIPAL, tenant=case.tenant):
            grades = await _grade(graders, sample)
    return CaseResult(
        id=case.id,
        passed=all(g.passed for g in grades),
        status=result.status,
        run_id=result.run_id,
        grades=tuple(grades),
        guards=guards,
        cost_usd=result.cost_usd,
    )


async def run_suite(target: EvalTarget, dataset: EvalDataset) -> SuiteResult:
    """Run every case of ``dataset`` in order and grade it.

    Raises:
        SpecError: For graders that can't be built.
        NotFound: For a task the harness doesn't have.
    """
    schema = target.output_schema(dataset.task)
    cases = [await _case(target, dataset, case, schema) for case in dataset.cases]
    return summarize(dataset.suite, dataset.task, dataset.thresholds.pass_rate, cases)


def shadow_guards(spec: HarnessSpec, task: str | None = None) -> list[str]:
    """The full names of the guards in shadow mode (``log_only``) that apply to ``task``."""
    return [
        name
        for name, guard in configured_guards(spec)
        if (guard.mode == "log_only" or guard.action == "log_only")
        and (task is None or not name.startswith("tasks.") or name.startswith(f"tasks.{task}."))
    ]


def suite_shadow_report(
    spec: HarnessSpec, dataset: EvalDataset, result: SuiteResult
) -> list[ShadowGuardReport]:
    """The shadow-guard report of one suite's run (R8)."""
    by_id = {case.id: case for case in dataset.cases}
    cases = [
        (case.id, dataset.graders_for(by_id[case.id]), case.guards)
        for case in result.cases
        if case.id in by_id
    ]
    return shadow_report(shadow_guards(spec, dataset.task), cases)
