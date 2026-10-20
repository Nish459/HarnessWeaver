"""``harness.wrap(agent)``: govern an app's existing Pydantic AI agent (DESIGNS No. 15).

Every run of the returned agent (``run``, ``run_sync``, ``iter``) carries a
:class:`~harnessweaver_pydantic_ai.capability.HarnessCapability`. Outside a
harness run, each agent run becomes a run of its own; inside one (a session, or
a session runner's handler), its model and tool calls are part of that run.

A call that needs the harness's approval escalates, as in a session, because the
harness can't resume the app's code; the ``pydantic_ai.agent`` runner can.
Streaming a wrapped agent is *planned* and raises for now (R4).
"""

from typing import Any

import harnessweaver as hw
from harnessweaver.adapters import Binding

__all__ = ["REACHES", "AgentAdapter"]

REACHES = (
    "run.start",
    "input.before",
    "model.before",
    "model.after",
    "tool.before",
    "tool.after",
    "output.before",
    "run.error",
    "run.end",
)


def conformance_sample() -> Any:
    """An offline agent and one run of it, for the conformance suite (T5)."""
    from harnessweaver_pydantic_ai.samples import adapter_sample

    return adapter_sample()


@hw.adapter(
    "agent",
    wraps=["pydantic_ai.Agent", "pydantic_ai.AbstractAgent"],
    reaches=REACHES,
    sample=conformance_sample,
)
class AgentAdapter:
    """Governs every run of a Pydantic AI agent."""

    def bind(self, target: Any, binding: Binding) -> Any:
        from harnessweaver_pydantic_ai.governed import GovernedAgent

        return GovernedAgent(target, binding)
