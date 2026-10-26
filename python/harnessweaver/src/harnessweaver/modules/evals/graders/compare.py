"""Graders that compare the output with the case's ``expect``."""

from typing import ClassVar

from pydantic import Field

from harnessweaver.core.evals import EvalSample, Grade
from harnessweaver.core.plugins import provider
from harnessweaver.modules.evals.graders.base import GraderConfig
from harnessweaver.modules.evals.values import MISSING, json_equal, value_at

__all__ = ["Exact", "FieldConfig", "FieldEquals", "NumericClose", "NumericConfig"]


@provider(port="Evaluator", name="exact", deterministic=True, latency_class="fast")
class Exact:
    """The output equals the case's ``expect`` (numbers by value, maps in any order)."""

    async def grade(self, sample: EvalSample) -> Grade:
        passed = json_equal(sample.output, sample.expect)
        return Grade.of(passed, None if passed else "the output differs from expect")


class FieldConfig(GraderConfig):
    SHORTHAND: ClassVar[str | None] = "field"

    field: str = Field(min_length=1, description="A dotted path: line_items.0.amount.")


@provider(
    port="Evaluator",
    name="field_equals",
    config=FieldConfig,
    deterministic=True,
    latency_class="fast",
    sample={"field": "total"},
)
class FieldEquals:
    """The output's ``field`` equals the same field of ``expect``."""

    def __init__(self, config: FieldConfig) -> None:
        self.field = config.field

    async def grade(self, sample: EvalSample) -> Grade:
        want = value_at(sample.expect, self.field)
        got = value_at(sample.output, self.field)
        if want is MISSING:
            return Grade.of(False, f"the case expects nothing at {self.field}")
        if got is MISSING:
            return Grade.of(False, f"the output has no {self.field}")
        passed = json_equal(got, want)
        return Grade.of(passed, None if passed else f"{self.field} differs")


class NumericConfig(GraderConfig):
    SHORTHAND: ClassVar[str | None] = "field"

    field: str | None = Field(default=None, min_length=1, description="None: the whole output.")
    tolerance: float = Field(default=1e-6, ge=0, description="The largest difference allowed.")


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


@provider(
    port="Evaluator",
    name="numeric_close",
    config=NumericConfig,
    deterministic=True,
    latency_class="fast",
)
class NumericClose:
    """The output's number (at ``field``) is within ``tolerance`` of ``expect``'s."""

    def __init__(self, config: NumericConfig | None = None) -> None:
        self.config = config or NumericConfig()

    async def grade(self, sample: EvalSample) -> Grade:
        field = self.config.field
        where = field or "the output"
        got = sample.output if field is None else value_at(sample.output, field)
        want = sample.expect if field is None else value_at(sample.expect, field)
        if not _is_number(want):
            return Grade.of(False, f"the case doesn't expect a number at {where}")
        if not _is_number(got):
            return Grade.of(False, f"{where} isn't a number")
        passed = abs(float(got) - float(want)) <= self.config.tolerance  # pyright: ignore[reportArgumentType]
        return Grade.of(passed, None if passed else f"{where} is off by more than the tolerance")
