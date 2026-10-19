"""``cel.policy``: policy rules in full CEL, evaluated by cel-python (DESIGNS No. 17).

The rules and how they combine are the same as the built-in ``cel_lite`` engine's
(``harnessweaver.decide_by_rules``, ADR-0025). Full CEL is stricter where
cel-lite relaxes it: ``1 + 2.5`` is an error here (ADR-0004), and an error in a
rule counts as unevaluable, so ``deny`` and ``require_approval`` rules apply.
"""

from typing import Any

import harnessweaver as hw
from harnessweaver.errors import SpecError

__all__ = ["CelPolicy"]


@hw.provider(
    port="PolicyEngine",
    name="cel.policy",
    config=hw.PolicyConfig,
    deterministic=True,
    latency_class="fast",
    sample={
        "rules": [
            {"id": "big", "when": "args.amount_usd > 100", "effect": "require_approval"},
            {"id": "contractors", "when": "'contractor' in principal.roles", "effect": "deny"},
        ]
    },
)
class CelPolicy:
    """Compiles every rule with cel-python when the harness loads, so a typo fails then (R4).

    Raises:
        SpecError: At construction, for a rule that isn't valid CEL.
    """

    def __init__(self, config: hw.PolicyConfig | None = None) -> None:
        # Imported on first use, so the plugin stays inert until a spec uses it (S8).
        import celpy
        from celpy.celparser import CELParseError

        self.config = config or hw.PolicyConfig()
        environment = celpy.Environment()
        self._programs: dict[int, Any] = {}
        for index, rule in enumerate(self.config.rules):
            try:
                program = environment.program(environment.compile(rule.when))
            except CELParseError:
                raise SpecError(f"policy.rules[{rule.id or index}].when isn't valid CEL") from None
            self._programs[id(rule)] = program

    async def decide(self, request: hw.PolicyRequest) -> hw.PolicyDecision:
        from celpy.adapter import json_to_cel
        from celpy.celtypes import BoolType
        from celpy.evaluation import CELEvalError

        activation = {name: json_to_cel(value) for name, value in request.variables().items()}

        def matches(rule: hw.PolicyRule) -> bool | None:
            try:
                result = self._programs[id(rule)].evaluate(activation)
            except CELEvalError:
                return None
            if not isinstance(result, BoolType):
                return None  # an error value, or not a bool: can't tell
            return bool(result)

        return hw.decide_by_rules(
            self.config.rules, self.config.default_effect, request.hook, matches
        )
