"""The ``validation`` module: business rules on outputs (DESIGNS No. 20).

Typed outputs are parsed and repaired by the runners (``validation.max_repairs``,
then ``validation.on_failure``). This module adds the spec's cel-lite business
rules as ``output.before`` middleware:

```yaml
validation:
  rules:
    - { id: no-negative-total, when: "output.total < 0", message: "the total can't be negative" }
```

A rule's ``when`` describes a violation, like a policy rule's ``when``. When it is
true, or can't be evaluated (a missing field, say), the middleware returns
``Retry`` with the rule's message, which asks the model for a repair.
"""

from typing import Any

from harnessweaver.core.bus import HookBus
from harnessweaver.core.context import current_run
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import ExpressionError
from harnessweaver.core.expr import Expression, compile_expression
from harnessweaver.core.hooks import Band, HookPoint, OutputEvent
from harnessweaver.core.middleware import Handler, Registration
from harnessweaver.core.outcomes import Outcome, Retry
from harnessweaver.modules.guardrails.pipeline import LAYER_BANDS
from harnessweaver.spec.loader import VALIDATION_VARIABLES, EffectiveSpec

__all__ = ["install_validation", "rule_handler"]


def rule_handler(expression: Expression, message: str) -> Handler:
    """Middleware that asks for a repair when ``expression`` is true for the output."""

    async def handle(event: OutputEvent, env: Envelope) -> Outcome | None:
        ctx = current_run()
        variables: dict[str, Any] = {
            "output": event.output,
            "input": ctx.input if ctx is not None else None,
            "task": {"name": env.task, "version": env.task_version},
        }
        try:
            violated = expression.evaluate_bool(variables)
        except ExpressionError:
            return Retry(reason=f"{message} (the rule couldn't be checked)")
        return Retry(reason=message) if violated else None

    return handle


def install_validation(effective: EffectiveSpec, bus: HookBus) -> int:
    """Install every ``validation.rules`` entry, banded by the layer that declared it."""
    added = 0
    for index, rule in enumerate(effective.spec.validation.rules):
        label = rule.id or str(index)
        path = f"validation.rules[{label}]"
        origin = effective.origin(f"{path}.id") or effective.origin(f"{path}.when")
        band = LAYER_BANDS[origin.kind] if origin is not None else Band.APP
        expression = compile_expression(rule.when, declared=VALIDATION_VARIABLES)
        bus.add(
            Registration(
                name=f"validation.rules[{label}]",
                handler=rule_handler(expression, rule.message),
                hooks=frozenset({HookPoint.OUTPUT_BEFORE}),
                band=band,
                fail_mode="closed",
            )
        )
        added += 1
    return added
