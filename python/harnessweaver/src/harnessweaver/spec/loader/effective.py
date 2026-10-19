"""``EffectiveSpec``: the validated spec with its layers, provenance, locks and bounds."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from harnessweaver.core.envelope import Budget
from harnessweaver.core.errors import (
    BoundViolation,
    SpecError,
)
from harnessweaver.spec.explain import ExplainRow, explain_rows, origin_of
from harnessweaver.spec.levels import LevelReport
from harnessweaver.spec.merge import (
    Bound,
    Lock,
    Provenance,
    check_bounds,
)
from harnessweaver.spec.models import HarnessSpec
from harnessweaver.spec.paths import parse_path

__all__ = ["EffectiveSpec"]


@dataclass(frozen=True, slots=True)
class EffectiveSpec:
    """An app's validated spec, with the layers, provenance, locks and bounds behind it."""

    spec: HarnessSpec
    data: Mapping[str, Any]
    provenance: Mapping[str, Provenance]
    locks: tuple[Lock, ...]
    bounds: tuple[Bound, ...]
    layers: tuple[Provenance, ...]
    level: LevelReport
    path: Path | None = None

    def origin(self, path: str) -> Provenance | None:
        """The layer that set ``path`` (for example ``budgets.per_run.max_usd``)."""
        return origin_of(parse_path(path), self.provenance)

    def explain(self) -> list[ExplainRow]:
        """Every effective value with its layer, lock and bounds (``spec explain``)."""
        return explain_rows(self.data, self.provenance, self.locks, self.bounds)

    def run_budget(self, task: str, overrides: Mapping[str, object] | None = None) -> Budget:
        """The budget for one run of ``task``: per-run limits, tightened by the task's own.

        ``overrides`` may only lower fields the task lists as ``overridable`` (R10).

        Raises:
            SpecError: If the task doesn't exist.
            BoundViolation: If an override isn't allowed, raises a limit, or breaks a bound.
        """
        if task not in self.spec.tasks:
            raise SpecError(f"unknown task {task!r}", task=task)
        task_spec = self.spec.tasks[task]
        budget = self.spec.budgets.per_run.intersect(task_spec.budget.to_budget())
        if not overrides:
            return budget
        for key in overrides:
            if key not in task_spec.budget.overridable:
                raise BoundViolation(
                    f"tasks.{task}.budget.{key} can't be overridden per run; "
                    f"overridable: {list(task_spec.budget.overridable)}",
                    path=f"tasks.{task}.budget.{key}",
                )
        try:
            lowered = Budget.model_validate({**budget.model_dump(), **overrides})
        except ValidationError as exc:
            raise BoundViolation(f"invalid budget override: {exc.error_count()} error(s)") from None
        for key in overrides:
            old, new = getattr(budget, key), getattr(lowered, key)
            if new is None or (old is not None and new > old):
                raise BoundViolation(
                    f"a run may only lower tasks.{task}.budget.{key} (R10)",
                    path=f"tasks.{task}.budget.{key}",
                )
        check_bounds({"budgets": {"per_run": lowered.model_dump(mode="json")}}, self.bounds, {})
        return lowered
