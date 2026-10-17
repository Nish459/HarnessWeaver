"""Adoption levels: what an effective spec reaches, and what its risk tier requires.

Levels are cumulative. Each requirement has a stable code, shared with the
``levels`` fixtures and reported by ``harnessweaver doctor``:

=====  ======================  =================================================
Level  Code                    Requirement
=====  ======================  =================================================
L0     (none)                  Observability is always on.
L1     L1.enforcing_guardrail  At least one enabled guardrail with mode enforce.
L1     L1.task_outputs         Every task declares an ``output``.
L2     L2.require_manifest     ``tools.require_manifest`` is true.
L2     L2.run_budget           ``budgets.per_run`` sets at least one limit.
L2     L2.policy_rules         ``policy.rules`` has at least one rule.
L3     L3.tasks                At least one task is defined.
L4     L4.task_evals           Every task has at least one eval suite.
=====  ======================  =================================================
"""

from dataclasses import dataclass
from typing import Final

from harnessweaver.spec.models import HarnessSpec, Level

__all__ = ["REQUIREMENTS", "LevelReport", "assess"]

REQUIREMENTS: Final[dict[str, str]] = {
    "L1.enforcing_guardrail": "at least one enabled guardrail with mode: enforce",
    "L1.task_outputs": "every task declares an output",
    "L2.require_manifest": "tools.require_manifest is true",
    "L2.run_budget": "budgets.per_run sets at least one limit",
    "L2.policy_rules": "policy.rules has at least one rule",
    "L3.tasks": "at least one task is defined",
    "L4.task_evals": "every task has at least one eval suite",
}
"""Requirement codes and their descriptions."""


@dataclass(frozen=True, slots=True)
class LevelReport:
    """The level a spec reaches, the level it must reach, and what is missing."""

    level: Level
    required: Level
    unmet: dict[Level, tuple[str, ...]]

    @property
    def ok(self) -> bool:
        return self.level.rank >= self.required.rank

    def missing_for(self, level: Level) -> list[str]:
        """Requirement codes still unmet for ``level`` and every level below it."""
        return [code for lvl in Level if lvl.rank <= level.rank for code in self.unmet.get(lvl, ())]


def _failures(spec: HarnessSpec) -> dict[Level, tuple[str, ...]]:
    tasks = spec.tasks.values()
    guards = list(spec.guardrails.all())
    for task in tasks:
        if task.guardrails is not None:
            guards.extend(task.guardrails.all())
    budget = spec.budgets.per_run
    suites = spec.evals.suites()
    checks: dict[Level, list[tuple[str, bool]]] = {
        Level.L1: [
            ("L1.enforcing_guardrail", any(g.enabled and g.mode == "enforce" for g in guards)),
            ("L1.task_outputs", all(t.output for t in tasks)),
        ],
        Level.L2: [
            ("L2.require_manifest", spec.tools.require_manifest),
            ("L2.run_budget", any(v is not None for v in budget.model_dump().values())),
            ("L2.policy_rules", bool(spec.policy.rules)),
        ],
        Level.L3: [("L3.tasks", bool(spec.tasks))],
        Level.L4: [("L4.task_evals", all(suites.get(name) for name in spec.tasks))],
    }
    return {level: tuple(code for code, ok in items if not ok) for level, items in checks.items()}


def assess(spec: HarnessSpec) -> LevelReport:
    """Work out the level ``spec`` reaches and the level its risk tier requires."""
    failures = _failures(spec)
    reached = Level.L0
    for level in (Level.L1, Level.L2, Level.L3, Level.L4):
        if failures[level]:
            break
        reached = level
    unmet = {
        level: codes for level, codes in failures.items() if level.rank > reached.rank and codes
    }
    required = spec.require_level.for_tier(spec.metadata.risk_tier)
    return LevelReport(reached, required, unmet)
