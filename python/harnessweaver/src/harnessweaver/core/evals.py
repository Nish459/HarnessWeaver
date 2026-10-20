"""Eval contracts: datasets, samples, grades, suite results and baselines (DESIGNS No. 23).

One dataset format serves CI and production sampling. A dataset names a suite
and the task its cases run, the graders every case gets, and the pass-rate
threshold. A grader is written as its name, or as a map from its name to its
settings:

```yaml
suite: golden
task: extract_invoice
graders:
  - schema_valid
  - { field_equals: invoice_number }
  - { numeric_close: { field: total, tolerance: 0.01 } }
thresholds: { pass_rate: 0.95 }
cases:
  - id: no-tax
    input: { text: "Invoice 7781 ..." }
    expect: { invoice_number: "7781", total: 50.00 }
    graders: [{ contains: "7781" }]        # added to the suite's graders
```

Each grader in a case is labelled so results, baselines and reports can name
it: ``name`` with no setting, ``name:value`` for a text, number or boolean
setting, and ``name#n`` for a list or map, where ``n`` counts that grader's uses
in the case's list (the suite's graders, then the case's own) from 1.
"""

import json
from collections.abc import Sequence
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from harnessweaver.core.guards import GuardAction
from harnessweaver.core.runs import RunStatus

__all__ = [
    "Baseline",
    "CaseResult",
    "Comparison",
    "EvalCase",
    "EvalDataset",
    "EvalSample",
    "Grade",
    "GraderItem",
    "GraderResult",
    "GraderSpec",
    "GuardFiring",
    "OnlineSample",
    "ShadowGuardReport",
    "SuiteResult",
    "Thresholds",
    "parse_graders",
]

type GraderItem = str | dict[str, JsonValue]
"""A grader as a dataset writes it: ``name``, or ``{name: settings}``."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- datasets ---------------------------------------------------------------------------------


class GraderSpec(_Model):
    """One grader of a case, read from its dataset form."""

    use: str = Field(min_length=1, description="The Evaluator provider.")
    settings: JsonValue = Field(
        default=None, description="As written: none, a value, a list or a map."
    )
    label: str = Field(min_length=1, description="How results and baselines name it.")


def _scalar_text(value: JsonValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, str):
        return value
    return json.dumps(value)


def parse_graders(items: Sequence[GraderItem]) -> tuple[GraderSpec, ...]:
    """Read graders as written and label them (see the module doc).

    Raises:
        ValueError: For a map without exactly one name, or a label used twice.
    """
    found: list[GraderSpec] = []
    uses: dict[str, int] = {}
    for item in items:
        if isinstance(item, str):
            use, settings = item, None
        elif len(item) == 1:
            ((use, settings),) = item.items()
        else:
            raise ValueError("a grader is a name, or a map with exactly one name")
        if not use:
            raise ValueError("a grader needs a name")
        uses[use] = uses.get(use, 0) + 1
        if settings is None:
            label = use
        elif isinstance(settings, list | dict):
            label = f"{use}#{uses[use]}"
        else:
            label = f"{use}:{_scalar_text(settings)}"
        if any(g.label == label for g in found):
            raise ValueError(f"grader {label} is listed twice")
        found.append(GraderSpec(use=use, settings=settings, label=label))
    return tuple(found)


class Thresholds(_Model):
    pass_rate: float = Field(default=1.0, ge=0, le=1, description="Share of cases that must pass.")


class EvalCase(_Model):
    """One case: the input the task runs on and what the graders compare against."""

    id: str = Field(min_length=1)
    description: str | None = None
    input: JsonValue = None
    expect: JsonValue = Field(default=None, description="What comparing graders expect.")
    graders: tuple[GraderItem, ...] = Field(default=(), description="Added to the suite's.")
    principal: str = Field(default="eval", min_length=1)
    tenant: str = Field(default="default", min_length=1)
    tags: tuple[str, ...] = ()


class EvalDataset(_Model):
    """A suite of cases for one task (DESIGNS No. 23)."""

    suite: str = Field(min_length=1)
    task: str = Field(min_length=1)
    description: str | None = None
    graders: tuple[GraderItem, ...] = Field(default=(), description="Every case gets these.")
    thresholds: Thresholds = Thresholds()
    cases: tuple[EvalCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _cases_are_gradable(self) -> Self:
        seen: set[str] = set()
        for case in self.cases:
            if case.id in seen:
                raise ValueError(f"case {case.id} is listed twice")
            seen.add(case.id)
            if not self.graders_for(case):
                raise ValueError(f"case {case.id} has no graders")
        return self

    def graders_for(self, case: EvalCase) -> tuple[GraderSpec, ...]:
        """The suite's graders followed by the case's own, labelled."""
        return parse_graders([*self.graders, *case.graders])


# --- samples and grades -----------------------------------------------------------------------


class GuardFiring(_Model):
    """A guard whose verdict wasn't ``allow``, read from the run's trace."""

    guard: str = Field(min_length=1, description="Its full name, like guardrails.input[pii].")
    action: GuardAction
    shadow: bool = Field(default=False, description="In log_only mode: it would have fired.")


class EvalSample(_Model):
    """What a grader sees: one run's outcome, and the case it ran for."""

    case: str | None = Field(default=None, description="The case id; none for online samples.")
    task: str | None = None
    input: JsonValue = None
    expect: JsonValue = Field(default=None, description="None for online samples.")
    output: JsonValue = None
    status: RunStatus = RunStatus.COMPLETED
    error_code: str | None = None
    guards: tuple[GuardFiring, ...] = ()
    output_schema: dict[str, JsonValue] | None = Field(
        default=None, description="The JSON Schema of the task's output, if it has one."
    )


class Grade(_Model):
    """What an ``Evaluator`` says about one sample."""

    passed: bool
    score: float = Field(ge=0, le=1)
    reason: str | None = Field(default=None, description="Names fields and rules, not content.")

    @classmethod
    def of(cls, passed: bool, reason: str | None = None) -> Self:
        """A pass or a fail, scored 1 or 0."""
        return cls(passed=passed, score=1.0 if passed else 0.0, reason=reason)


class GraderResult(Grade):
    grader: str = Field(min_length=1, description="The grader's label.")


class CaseResult(_Model):
    id: str = Field(min_length=1)
    passed: bool
    status: RunStatus
    run_id: str | None = None
    grades: tuple[GraderResult, ...] = ()
    guards: tuple[GuardFiring, ...] = ()
    cost_usd: float | None = Field(default=None, ge=0)


class SuiteResult(_Model):
    """A suite's cases, its pass rate and whether it meets its threshold."""

    suite: str = Field(min_length=1)
    task: str = Field(min_length=1)
    threshold: float = Field(ge=0, le=1)
    pass_rate: float = Field(ge=0, le=1, description="To 6 decimal places.")
    passed: bool = Field(description="pass_rate >= threshold.")
    grader_rates: dict[str, float] = Field(
        default_factory=dict[str, float], description="Share of cases each grader passed."
    )
    cases: tuple[CaseResult, ...] = ()


# --- baselines and reports --------------------------------------------------------------------


class Baseline(_Model):
    """A suite's accepted results: ``.harness/baselines/<task>.<suite>.json``."""

    suite: str = Field(min_length=1)
    task: str = Field(min_length=1)
    pass_rate: float = Field(ge=0, le=1)
    cases: dict[str, bool] = Field(default_factory=dict[str, bool], description="Passed, by id.")


class Comparison(_Model):
    """How a suite's results differ from its baseline; ids are sorted."""

    regressed: tuple[str, ...] = Field(default=(), description="Passed before, fail now.")
    fixed: tuple[str, ...] = Field(default=(), description="Failed before, pass now.")
    added: tuple[str, ...] = Field(default=(), description="Not in the baseline.")
    removed: tuple[str, ...] = Field(default=(), description="Only in the baseline.")

    @property
    def regression(self) -> bool:
        return bool(self.regressed)


class ShadowGuardReport(_Model):
    """How often a ``log_only`` guard would have fired, and how well (R8)."""

    guard: str = Field(min_length=1)
    runs: int = Field(ge=0)
    would_fire: int = Field(ge=0)
    rate: float = Field(ge=0, le=1, description="would_fire / runs, to 6 decimal places.")
    false_positives: tuple[str, ...] | None = Field(
        default=None, description="Cases it would fire on that don't expect it; none online."
    )
    misses: tuple[str, ...] | None = Field(
        default=None, description="Cases that expect it where it wouldn't fire; none online."
    )


class OnlineSample(_Model):
    """A production run sampled at ``run.end`` and graded (``evals.online``).

    It names the run instead of copying its content: the run's record holds that.
    """

    run_id: str = Field(min_length=1)
    task: str | None = None
    tenant: str = Field(min_length=1)
    at: AwareDatetime
    status: RunStatus
    grades: tuple[GraderResult, ...] = ()
    guards: tuple[GuardFiring, ...] = ()
