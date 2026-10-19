"""Session style: the app owns the flow, the harness owns the clients (DESIGNS No. 15).

Every capability a session offers is governed: ``generate`` fires ``model.*``
and ``output.before``, ``tool`` fires ``tool.*``, ``decide`` fires
``route.decide``, and so on. A halting outcome raises a
:class:`~harnessweaver.errors.RunInterrupted` error in the app's code
(ADR-0020).

Example:
    >>> async with harness.session(task="support", principal=user) as s:  # doctest: +SKIP
    ...     route = await s.decide("support_router", text=question)
    ...     answer = await s.generate(prompt="support_answer@4", output=CitedAnswer,
    ...                               question=question)
"""

from collections.abc import Iterable, Sequence
from datetime import timedelta
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, Self

from pydantic import BaseModel, JsonValue

from harnessweaver.core.context import RunContext
from harnessweaver.core.decisions import Decision, DecisionRequest
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import SpecError, ValidationFailed
from harnessweaver.core.ids import new_id
from harnessweaver.core.messages import Message, ModelRequest, ToolCall
from harnessweaver.core.outcomes import Retry
from harnessweaver.core.ports import Memory
from harnessweaver.core.results import RunResult
from harnessweaver.core.retrieval import ContextItem
from harnessweaver.core.trace import RunTrace
from harnessweaver.runners._output import (
    candidate_of,
    check_output,
    give_up,
    parse_output,
    repair_message,
    schema_of,
    text_of,
    to_json,
)

if TYPE_CHECKING:
    from harnessweaver.harness import Harness, PendingSession

__all__ = ["ContextSource", "Session", "SessionMemory"]


class ContextSource:
    """Governed access to one context source (``s.context("kb")``)."""

    def __init__(self, ctx: RunContext, source: str) -> None:
        self._ctx = ctx
        self.source = source

    async def fetch(self, query: str, *, limit: int | None = None) -> tuple[ContextItem, ...]:
        """Retrieve from the source's provider: ACLs re-checked, labelled, capped, then
        ``context.after`` (DESIGNS No. 21).

        Raises:
            SpecError: For a source the spec doesn't name.
        """
        return await self._ctx.fetch_context(self.source, query, limit=limit)

    async def check(
        self, items: Iterable[ContextItem], *, query: str | None = None
    ) -> tuple[ContextItem, ...]:
        """Fire ``context.after`` on items the app retrieved itself.

        Middleware may filter or relabel them; untrusted items label the run (S3).
        """
        return await self._ctx.context_after(self.source, items, query=query)


class SessionMemory:
    """Key-value entries kept for the run's tenant, principal and task (``s.memory``).

    Entries expire after ``ttl``, or the spec's ``memory.default_ttl``; times come
    from the run's clock. Another tenant, principal or task never sees them.
    """

    def __init__(self, ctx: RunContext) -> None:
        self._ctx = ctx

    @property
    def _store(self) -> Memory:
        if self._ctx.memory is None:
            raise SpecError("this run has no memory provider")
        return self._ctx.memory

    @property
    def namespace(self) -> tuple[str, ...]:
        envelope = self._ctx.envelope
        return (envelope.tenant, envelope.principal.id, envelope.task or "")

    async def put(self, key: str, value: JsonValue, *, ttl: timedelta | None = None) -> None:
        """Keep ``value`` under ``key``, replacing what was there."""
        lifetime = ttl if ttl is not None else self._ctx.memory_ttl
        expires = self._ctx.clock.now() + lifetime if lifetime is not None else None
        await self._store.put(self.namespace, key, value, expires_at=expires)

    async def get(self, key: str) -> JsonValue | None:
        """The value under ``key``, or ``None`` if there is none or it expired."""
        return await self._store.get(self.namespace, key, now=self._ctx.clock.now())

    async def delete(self, key: str) -> None:
        await self._store.delete(self.namespace, key)

    async def entries(self) -> dict[str, JsonValue]:
        """Every entry that hasn't expired."""
        return await self._store.entries(self.namespace, now=self._ctx.clock.now())


class Session:
    """Governed model, tool, routing and validation calls inside one run.

    Get one from ``harness.session(...)`` (standalone: the session is the run)
    or as the first argument of a ``session``/``workflow`` runner handler.
    """

    def __init__(
        self,
        ctx: RunContext | None,
        *,
        harness: "Harness | None" = None,
        pending: "PendingSession | None" = None,
        step: str | None = None,
    ) -> None:
        self._bound = ctx
        self._harness = harness
        self._pending = pending
        self.step = step
        self.result: RunResult | None = None
        """For a standalone session, the run's result once the ``async with`` exits."""

    @classmethod
    def for_run(cls, ctx: RunContext, *, step: str | None = None) -> Self:
        """A session view of a run the harness is driving (for runner handlers)."""
        return cls(ctx, step=step)

    # --- standalone lifecycle ---------------------------------------------------------------

    @property
    def _ctx(self) -> RunContext:
        if self._bound is None:
            raise SpecError("use the session inside 'async with harness.session(...)'")
        return self._bound

    async def __aenter__(self) -> Self:
        if self._harness is None or self._pending is None or self._bound is not None:
            raise SpecError("only a new harness.session(...) can be entered")
        try:
            self._bound = await self._harness._open_session(self._pending)  # pyright: ignore[reportPrivateUsage]
        except BaseException:
            self.result = self._pending.result
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Never suppresses: halts and app errors reach the app's code (ADR-0020).
        assert self._harness is not None
        assert self._pending is not None
        self.result = await self._harness._close_session(self._pending, exc)  # pyright: ignore[reportPrivateUsage]

    # --- state ------------------------------------------------------------------------------

    @property
    def envelope(self) -> Envelope:
        return self._ctx.envelope

    @property
    def run_id(self) -> str:
        return self._ctx.run_id

    @property
    def trace(self) -> RunTrace:
        return self._ctx.trace

    @property
    def run_context(self) -> RunContext:
        """The underlying run context, for adapters."""
        return self._ctx

    # --- governed operations ----------------------------------------------------------------

    async def prompt(self, ref: str, /, **variables: Any) -> str:
        """Render a versioned prompt (ADR-0013)."""
        if self._ctx.prompts is None:
            raise SpecError("no prompts are configured")
        return await self._ctx.prompts.render(ref, variables)

    async def generate(
        self,
        *,
        prompt: str | None = None,
        messages: Sequence[Message] = (),
        model: str | None = None,
        output: type[Any] | None = None,
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **variables: Any,
    ) -> Any:
        """Ask the model for an answer, governed end to end.

        ``prompt`` is rendered with ``variables`` and sent as a user message after
        ``messages``. With ``output``, the answer is parsed into that type and
        repaired up to ``validation.max_repairs`` times.

        Raises:
            RunInterrupted: When a hook or a budget halts the run.
            ProviderError: When the model provider fails.
        """
        history = list(messages)
        if prompt is not None:
            history.append(Message.user(await self.prompt(prompt, **variables)))
        if not history:
            raise SpecError("generate needs a prompt or messages")
        task = self._ctx.task
        max_repairs = task.max_repairs if task is not None else 1
        attempt = 0
        while True:
            request = ModelRequest(
                alias=model,
                messages=tuple(history),
                output_schema=schema_of(output),
                stream=stream,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            response = await self._ctx.generate(request)
            candidate = candidate_of(response)
            value, problem = parse_output(candidate, output)
            if problem is None:
                value, problem = await check_output(self._ctx, value, output, attempt)
            if problem is None:
                self._ctx.output = to_json(value)
                return value
            if attempt >= max_repairs:
                give_up(self._ctx, problem, attempt)
            attempt += 1
            history += [
                Message.assistant(text_of(candidate), extensions=response.extensions),
                repair_message(self._ctx, problem, attempt),
            ]

    async def tool(self, name: str, /, **arguments: JsonValue) -> JsonValue:
        """Call a tool, governed (``tool.before`` / ``tool.after``). Returns its output."""
        call = ToolCall(id=new_id("call"), name=name, arguments=arguments)
        result = await self._ctx.call_tool(call)
        return result.output

    async def decide(
        self,
        router: str,
        *,
        text: str | None = None,
        options: Iterable[str] = (),
        state: dict[str, JsonValue] | None = None,
        default: str | None = None,
    ) -> Decision:
        """Ask the routing middleware to choose (``route.decide``)."""
        request = DecisionRequest(
            router=router, text=text, options=tuple(options), state=state or {}
        )
        return await self._ctx.decide(request, default=default)

    def context(self, source: str) -> ContextSource:
        """Governed access to a context source."""
        return ContextSource(self._ctx, source)

    @property
    def memory(self) -> SessionMemory:
        """Entries kept for this tenant, principal and task (DESIGNS No. 21)."""
        return SessionMemory(self._ctx)

    async def guard(self, stage: Literal["input"], content: JsonValue) -> JsonValue:
        """Run the input guards on content the app received (``input.before``)."""
        if stage != "input":
            raise SpecError(f"unknown guard stage {stage!r}; use validate() for output")
        return await self._ctx.check_input(content)

    async def validate(self, stage: Literal["output"], value: Any) -> Any:
        """Check a final output (``output.before``). Returns it, possibly modified.

        Raises:
            ValidationFailed: When a middleware asks for a repair; in session
                style the app decides how to repair.
            RunInterrupted: When a hook halts the run.
        """
        if stage != "output":
            raise SpecError(f"unknown validation stage {stage!r}")
        result = await self._ctx.check_output(to_json(value))
        if isinstance(result.outcome, Retry):
            raise ValidationFailed(result.outcome.reason)
        final: Any = result.event.output
        if isinstance(value, BaseModel) and final != to_json(value):
            final = type(value).model_validate(final)
        elif final == to_json(value):
            final = value
        self._ctx.output = to_json(final)
        return final
