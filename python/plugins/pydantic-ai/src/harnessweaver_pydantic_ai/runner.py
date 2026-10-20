"""The ``pydantic_ai.agent`` runner: a task run by a Pydantic AI agent (DESIGNS No. 15).

```yaml
tasks:
  billing_agent:
    runner: { use: pydantic_ai.agent, agent: "app.agents:billing_agent" }
    tools: [refund_payment]             # offered to the agent next to its own tools
```

The harness owns the run: idempotency, deadlines, ``run.start``, ``input.before``,
approvals and ``run.end``. The agent runs inside it with
:class:`~harnessweaver_pydantic_ai.capability.HarnessCapability`, which governs
every model request, tool call and the final output. By default the agent's
requests go to the harness's model provider (``models`` in the spec), so the
gateway owns keys and retries (R5); ``model: agent`` keeps the agent's own model,
still governed.

A tool call that needs approval suspends the run; ``harness.approve()`` resumes the
agent with Pydantic AI's deferred tool results (ADR-0037).
"""

import importlib
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

import harnessweaver as hw
from harnessweaver.errors import SpecError

__all__ = ["REACHES", "AgentRunner", "AgentRunnerConfig", "import_target"]

REACHES = (
    "run.start",
    "input.before",
    "model.before",
    "model.after",
    "tool.before",
    "tool.after",
    "output.before",
    "approval.resolved",
    "run.error",
    "run.end",
)


def import_target(path: str, where: str) -> Any:
    """Import ``'package.module:attribute'``.

    Raises:
        SpecError: If it can't be imported.
    """
    module, _, attribute = path.partition(":")
    if not module or not attribute:
        raise SpecError(f"{where}: {path!r} isn't 'package.module:attribute'")
    try:
        return getattr(importlib.import_module(module), attribute)
    except (ImportError, AttributeError) as exc:
        raise SpecError(f"{where}: can't import {path!r} ({type(exc).__name__})") from None


class AgentRunnerConfig(BaseModel):
    """Settings for ``runner: {use: pydantic_ai.agent, ...}``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent: str = Field(description="'package.module:attribute' of a Pydantic AI agent.")
    model: Literal["harness", "agent"] = Field(
        default="harness",
        description="harness: the spec's models answer (the default); agent: the agent's own "
        "model does, governed the same way.",
    )
    deps: str | None = Field(
        default=None,
        description="'package.module:function' called with (session, input) that returns the "
        "agent's deps.",
    )


@hw.runner(
    "agent",
    reaches=REACHES,
    config=AgentRunnerConfig,
    resumable=True,
    sample={"agent": "harnessweaver_pydantic_ai.samples:agent"},
)
class AgentRunner:
    """Run a task with a Pydantic AI agent, governed by the harness."""

    def __init__(self, config: AgentRunnerConfig) -> None:
        from pydantic_ai.agent import AbstractAgent

        self.config = config
        self.agent: Any = import_target(config.agent, "runner.agent")
        if not isinstance(self.agent, AbstractAgent):
            raise SpecError(f"runner.agent: {config.agent!r} isn't a Pydantic AI agent")
        self.deps: Any = import_target(config.deps, "runner.deps") if config.deps else None
        if self.deps is not None and not callable(self.deps):
            raise SpecError(f"runner.deps: {config.deps!r} isn't callable")

    async def execute(
        self, ctx: hw.RunContext, input: Any, resume: Mapping[str, JsonValue] | None
    ) -> Any:
        from harnessweaver_pydantic_ai.running import run_agent

        return await run_agent(self, ctx, input, resume)
