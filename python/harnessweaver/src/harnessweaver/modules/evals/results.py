"""Summaries, baseline comparisons, the shadow-guard report and online sampling
(DESIGNS No. 23, fixtures suite ``evals``)."""

from collections.abc import Iterable, Mapping, Sequence

from harnessweaver.core.evals import (
    Baseline,
    CaseResult,
    Comparison,
    GraderSpec,
    GuardFiring,
    OnlineSample,
    ShadowGuardReport,
    SuiteResult,
)
from harnessweaver.core.guards import GuardAction
from harnessweaver.core.text import fnv1a32
from harnessweaver.core.trace import TraceEvent
from harnessweaver.modules.evals.graders import GuardFiredConfig, guard_matches

__all__ = ["compare", "firings", "online_shadow_report", "sampled", "shadow_report", "summarize"]


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 6) if whole else 0.0


def summarize(suite: str, task: str, threshold: float, cases: Sequence[CaseResult]) -> SuiteResult:
    """A suite's pass rate (to 6 decimals), whether it meets ``threshold`` (compared
    before rounding) and each grader's pass rate over the cases that have it."""
    passed = sum(1 for case in cases if case.passed)
    totals: dict[str, list[int]] = {}
    for case in cases:
        for grade in case.grades:
            counts = totals.setdefault(grade.grader, [0, 0])
            counts[0] += grade.passed
            counts[1] += 1
    return SuiteResult(
        suite=suite,
        task=task,
        threshold=threshold,
        pass_rate=_rate(passed, len(cases)),
        passed=bool(cases) and passed / len(cases) >= threshold,
        grader_rates={label: _rate(ok, of) for label, (ok, of) in totals.items()},
        cases=tuple(cases),
    )


def compare(baseline: Baseline | None, cases: Mapping[str, bool]) -> Comparison:
    """How ``cases`` (passed, by id) differ from ``baseline``. A case that passed in the
    baseline and fails now is a regression."""
    before = baseline.cases if baseline is not None else {}
    return Comparison(
        regressed=tuple(sorted(i for i, ok in cases.items() if before.get(i) is True and not ok)),
        fixed=tuple(sorted(i for i, ok in cases.items() if before.get(i) is False and ok)),
        added=tuple(sorted(i for i in cases if i not in before)),
        removed=tuple(sorted(i for i in before if i not in cases)),
    )


def sampled(run_id: str, rate: float) -> bool:
    """Whether online evals sample this run: FNV-1a 32 of the id's UTF-8 bytes, over
    2^32, is below ``rate``. Every language and process agrees."""
    return rate > 0 and fnv1a32(run_id.encode("utf-8")) / 2**32 < rate


def firings(trace: Iterable[TraceEvent]) -> tuple[GuardFiring, ...]:
    """The guards that fired in a run, or would have in shadow mode, once each."""
    found: list[GuardFiring] = []
    for event in trace:
        if event.source != "harness.guard" or event.code not in ("guard_fired", "guard_shadow"):
            continue
        firing = GuardFiring(
            guard=str(event.details["guard"]),
            action=GuardAction(str(event.details["action"])),
            shadow=event.code == "guard_shadow",
        )
        if firing not in found:
            found.append(firing)
    return tuple(found)


def _expected(graders: Sequence[GraderSpec], guard: str) -> bool:
    for spec in graders:
        if spec.use != "guard_fired":
            continue
        settings = spec.settings if isinstance(spec.settings, dict) else {"guard": spec.settings}
        config = GuardFiredConfig.model_validate(settings)
        if config.fired and any(guard_matches(guard, wanted) for wanted in config.guards):
            return True
    return False


def _would_fire(guard: str, fired: Sequence[GuardFiring]) -> bool:
    return any(f.shadow and f.guard == guard for f in fired)


def shadow_report(
    guards: Sequence[str], cases: Sequence[tuple[str, Sequence[GraderSpec], Sequence[GuardFiring]]]
) -> list[ShadowGuardReport]:
    """For each ``log_only`` guard: how many cases it would fire on, the rate, and the
    false positives and misses against what each case's ``guard_fired`` graders
    expect. A case that doesn't name the guard expects it not to fire (R8)."""
    report: list[ShadowGuardReport] = []
    for guard in guards:
        fired = [case for case, _, f in cases if _would_fire(guard, f)]
        expected = {case for case, graders, _ in cases if _expected(graders, guard)}
        report.append(
            ShadowGuardReport(
                guard=guard,
                runs=len(cases),
                would_fire=len(fired),
                rate=_rate(len(fired), len(cases)),
                false_positives=tuple(c for c in fired if c not in expected),
                misses=tuple(c for c, _, _ in cases if c in expected and c not in fired),
            )
        )
    return report


def online_shadow_report(
    guards: Sequence[str], samples: Sequence[OnlineSample]
) -> list[ShadowGuardReport]:
    """The would-fire rate of each ``log_only`` guard over production samples, which
    have no expectations to find false positives with."""
    return [
        ShadowGuardReport(
            guard=guard,
            runs=len(samples),
            would_fire=(count := sum(1 for s in samples if _would_fire(guard, s.guards))),
            rate=_rate(count, len(samples)),
        )
        for guard in guards
    ]
