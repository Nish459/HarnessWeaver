"""The ``session`` runner: the app's own function runs inside a harness-owned run.

``runner: {use: session, handler: "app.flows:answer"}`` calls
``await answer(s, input)`` with a :class:`~harnessweaver.Session`. The harness
owns the lifecycle around it: idempotency, deadlines, run hooks and approvals.

After an approval the handler runs again from the start; the approved call is
recognized by its tool name and arguments and passes without asking again. Work
before the suspension point should therefore be safe to repeat (DESIGNS No. 18).
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from harnessweaver._imports import import_object
from harnessweaver.core.context import RunContext
from harnessweaver.core.plugins import runner
from harnessweaver.runners.direct import ALL_HOOKS
from harnessweaver.session import Session

__all__ = ["SessionRunner", "SessionRunnerConfig"]


class SessionRunnerConfig(BaseModel):
    """Settings for ``runner: {use: session, handler: ...}``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    handler: str = Field(description="'package.module:function' taking (session, input).")


@runner("session", reaches=ALL_HOOKS, config=SessionRunnerConfig)
class SessionRunner:
    """Call an app function with a governed session."""

    def __init__(self, config: SessionRunnerConfig) -> None:
        self.handler = import_object(config.handler, "runner.handler")

    async def execute(
        self, ctx: RunContext, input: Any, resume: Mapping[str, JsonValue] | None
    ) -> Any:
        return await self.handler(Session.for_run(ctx), input)
