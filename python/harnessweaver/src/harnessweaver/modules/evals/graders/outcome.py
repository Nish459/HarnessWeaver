"""Graders of how the run ended: ``schema_valid``, ``guard_fired``, ``status``."""

from typing import ClassVar, Self

from pydantic import Field, field_validator, model_validator

from harnessweaver.core.evals import EvalSample, Grade
from harnessweaver.core.guards import GuardAction
from harnessweaver.core.jsonschema import SchemaError, check_schema, validate
from harnessweaver.core.plugins import provider
from harnessweaver.core.runs import RunStatus
from harnessweaver.modules.evals.graders.base import GraderConfig, nonempty, texts

__all__ = [
    "GuardFired",
    "GuardFiredConfig",
    "SchemaValid",
    "Status",
    "StatusConfig",
    "guard_matches",
]


@provider(port="Evaluator", name="schema_valid", deterministic=True, latency_class="fast")
class SchemaValid:
    """The run completed and its output matches the task's output schema (ADR-0026);
    without a schema, the run completed with an output."""

    async def grade(self, sample: EvalSample) -> Grade:
        if sample.status is not RunStatus.COMPLETED:
            return Grade.of(False, f"the run ended {sample.status.value}")
        schema = sample.output_schema
        if schema is None:
            found = sample.output is not None
            return Grade.of(found, None if found else "the run has no output")
        try:
            check_schema(schema)
        except SchemaError as exc:
            return Grade.of(False, f"the task's output schema can't be checked: {exc}")
        problems = validate(sample.output, schema)
        return Grade.of(not problems, "; ".join(problems) or None)


def guard_matches(name: str, wanted: str) -> bool:
    """Whether a guard's full name is ``wanted``, or ends with ``[wanted]``."""
    return name == wanted or name.endswith(f"[{wanted}]")


class GuardFiredConfig(GraderConfig):
    SHORTHAND: ClassVar[str | None] = "guard"

    guard: str | tuple[str, ...] = Field(description="Guard ids or full names.")
    fired: bool = Field(default=True, description="False: the guards must not fire.")
    action: GuardAction | None = Field(default=None, description="Only this action counts.")

    @field_validator("guard")
    @classmethod
    def _some_guard(cls, value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        return nonempty(value)

    @property
    def guards(self) -> tuple[str, ...]:
        return texts(self.guard)


@provider(
    port="Evaluator",
    name="guard_fired",
    config=GuardFiredConfig,
    deterministic=True,
    latency_class="fast",
    sample={"guard": "pii"},
)
class GuardFired:
    """Each listed guard fired in the run (or would have, in shadow mode); with
    ``fired: false``, none did."""

    def __init__(self, config: GuardFiredConfig) -> None:
        self.config = config

    async def grade(self, sample: EvalSample) -> Grade:
        action = self.config.action
        wrong = [
            wanted
            for wanted in self.config.guards
            if any(
                guard_matches(f.guard, wanted) and (action is None or f.action is action)
                for f in sample.guards
            )
            is not self.config.fired
        ]
        if not wrong:
            return Grade.of(True)
        verb = "didn't fire" if self.config.fired else "fired"
        return Grade.of(False, f"{', '.join(wrong)} {verb}")


class StatusConfig(GraderConfig):
    SHORTHAND: ClassVar[str | None] = "status"

    status: RunStatus | tuple[RunStatus, ...]

    @model_validator(mode="after")
    def _some(self) -> Self:
        if isinstance(self.status, tuple) and not self.status:
            raise ValueError("give at least one status")
        return self


@provider(
    port="Evaluator",
    name="status",
    config=StatusConfig,
    deterministic=True,
    latency_class="fast",
    sample={"status": "completed"},
)
class Status:
    """The run ended with one of the listed statuses (``blocked`` for red-team cases)."""

    def __init__(self, config: StatusConfig) -> None:
        status = config.status
        self.statuses = (status,) if isinstance(status, RunStatus) else status

    async def grade(self, sample: EvalSample) -> Grade:
        passed = sample.status in self.statuses
        return Grade.of(passed, None if passed else f"the run ended {sample.status.value}")
