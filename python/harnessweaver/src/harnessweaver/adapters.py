"""Wrap style: adapters that govern an existing client or framework (DESIGNS No. 15).

``harness.instrument(client)`` and ``harness.wrap(agent)`` find an adapter for
the target's type and return a governed stand-in. Each model call it makes goes
through the harness:

* inside a run or session, the call is one governed model call of that run;
* otherwise it becomes a small run of its own: ``run.start``, ``input.before`` on
  the messages, ``model.before``, the call, ``model.after``, ``output.before`` on
  the answer, and ``run.end``. That is what gives an L0 app traces, cost and the
  error taxonomy, and an L1 app its input and output guards, without changing
  its code.

A halting outcome is raised in the app's code as a ``RunInterrupted`` error
(ADR-0020); a repair request at ``output.before`` is raised as
``ValidationFailed``, since the app owns the flow.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import anyio

from harnessweaver.core.context import RunContext, current_run
from harnessweaver.core.envelope import Principal
from harnessweaver.core.errors import SpecError, ValidationFailed
from harnessweaver.core.messages import Message, ModelRequest, ModelResponse
from harnessweaver.core.outcomes import Retry
from harnessweaver.core.ports import ModelProvider

if TYPE_CHECKING:
    from harnessweaver.harness import Harness

__all__ = ["Adapter", "Binding", "CallProvider", "run_sync"]


class Adapter(Protocol):
    """What an ``@hw.adapter`` class does: return a governed stand-in for ``target``."""

    def bind(self, target: Any, binding: "Binding") -> Any: ...


class CallProvider:
    """A one-off model provider: the adapter's own call to the client it wraps.

    ``call`` receives the request after ``model.before`` (so redactions and alias
    changes apply) and returns the neutral response.
    """

    def __init__(self, call: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> None:
        self._call = call

    async def generate(self, request: ModelRequest, env: Any) -> ModelResponse:
        return await self._call(request)


@dataclass(frozen=True, slots=True)
class Binding:
    """What ``harness.instrument()`` and ``harness.wrap()`` give an adapter: how to make
    governed calls, and the task, principal, tenant and attributes of the runs they make."""

    harness: "Harness"
    task: str | None = None
    principal: Principal | str = "anonymous"
    tenant: str = "default"
    attributes: Mapping[str, str] = field(default_factory=dict[str, str])

    async def generate(self, request: ModelRequest, provider: ModelProvider) -> ModelResponse:
        """Make one governed call through ``provider`` (see the module doc).

        Raises:
            RunInterrupted: When a hook or a budget halts the call.
            ValidationFailed: When output middleware asks for a repair.
        """
        ctx = current_run()
        if ctx is not None:
            return await ctx.generate(request, provider=provider)
        async with self.harness.session(
            self.task,
            principal=self.principal,
            tenant=self.tenant,
            attributes=self.attributes,
        ) as session:
            return await _standalone(session.run_context, request, provider)


async def _standalone(
    ctx: RunContext, request: ModelRequest, provider: ModelProvider
) -> ModelResponse:
    contents = [message.content for message in request.messages]
    checked = await ctx.check_input(list[Any](contents))
    if checked != contents:
        if not (
            isinstance(checked, list)
            and len(checked) == len(contents)
            and all(isinstance(c, str) for c in checked)
        ):
            raise SpecError("input middleware must keep one text per message")
        messages = tuple(
            Message.model_validate({**m.model_dump(), "content": c})
            for m, c in zip(request.messages, checked, strict=True)
        )
        request = request.model_copy(update={"messages": messages})
    ctx.input = list[Any](checked) if isinstance(checked, list) else checked
    response = await ctx.generate(request, provider=provider)
    if response.text:
        result = await ctx.check_output(response.text)
        if isinstance(result.outcome, Retry):
            raise ValidationFailed(result.outcome.reason)
        if isinstance(result.event.output, str) and result.event.output != response.text:
            response = response.model_copy(update={"text": result.event.output})
    ctx.output = response.text
    return response


def run_sync[T](make: Callable[[], Awaitable[T]]) -> T:
    """Run a governed call from synchronous code (for sync clients).

    Raises:
        SpecError: When called from inside a running event loop; use the client's
            async variant there.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return anyio.run(make)
    raise SpecError("a sync client can't be governed inside an event loop; use its async client")
