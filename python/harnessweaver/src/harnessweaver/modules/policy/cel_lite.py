"""``cel_lite``: the built-in policy engine, with rules in cel-lite (ADR-0004)."""

from harnessweaver.core.errors import ExpressionEvalError, ExpressionSyntaxError, SpecError
from harnessweaver.core.expr import Expression, compile_expression
from harnessweaver.core.plugins import provider
from harnessweaver.core.policy import (
    RUN_POLICY_VARIABLES,
    TOOL_POLICY_VARIABLES,
    PolicyConfig,
    PolicyDecision,
    PolicyRequest,
    PolicyRule,
    decide_by_rules,
)

__all__ = ["CelLitePolicy"]


def _compile(rule: PolicyRule, index: int) -> Expression:
    names = TOOL_POLICY_VARIABLES if rule.hook == "tool.before" else RUN_POLICY_VARIABLES
    try:
        return compile_expression(rule.when, declared=names)
    except ExpressionSyntaxError as exc:
        raise SpecError(f"policy.rules[{rule.id or index}].when: {exc.message}") from None


@provider(
    port="PolicyEngine",
    name="cel_lite",
    config=PolicyConfig,
    deterministic=True,
    latency_class="fast",
    sample={
        "rules": [
            {"id": "big", "when": "args.amount_usd > 100", "effect": "require_approval"},
            {"id": "contractors", "when": "'contractor' in principal.roles", "effect": "deny"},
        ]
    },
)
class CelLitePolicy:
    """Rules in cel-lite, compiled when the harness loads so a typo fails then (R4).

    Raises:
        SpecError: At construction, for a rule that doesn't compile.
    """

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()
        self._compiled = {
            id(rule): _compile(rule, index) for index, rule in enumerate(self.config.rules)
        }

    async def decide(self, request: PolicyRequest) -> PolicyDecision:
        variables = request.variables()

        def matches(rule: PolicyRule) -> bool | None:
            try:
                return self._compiled[id(rule)].evaluate_bool(variables)
            except ExpressionEvalError:
                return None

        return decide_by_rules(self.config.rules, self.config.default_effect, request.hook, matches)
