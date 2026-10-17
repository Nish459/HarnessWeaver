"""RunContext: the mutable state of one run, and the governed operations runners use.

Runners, sessions and adapters never call a model, a tool or a guard directly.
They call the methods here, which fire the hook points around each operation,
apply budgets and deadlines, and turn halting outcomes into
:class:`~harnessweaver.errors.RunInterrupted` errors (ADR-0020). That is how one
set of controls covers every integration style (DESIGNS No. 7, No. 15).

The envelope stays immutable: when labels or the budget change, the context
produces a new one (DESIGNS No. 10).
"""

import contextlib
import logging
from collections.abc import Callable, Generator, Iterable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, NoReturn, Protocol

from pydantic import JsonValue

from harnessweaver.core.budgets import BudgetMeter, PriceLookup, breach_block, resolve_cost
from harnessweaver.core.bus import HookBus, HookResult
from harnessweaver.core.decisions import Decision, DecisionRequest
from harnessweaver.core.envelope import Clock, Envelope
from harnessweaver.core.errors import (
    DeadlineExceeded,
    HarnessError,
    ProviderError,
    RunBlocked,
    RunEscalated,
    RunInterrupted,
    RunSuspended,
    SpecError,
)
from harnessweaver.core.hooks import (
    ApprovalResolvedEvent,
    ContextEvent,
    HookPoint,
    InputEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    OutputEvent,
    RouteEvent,
    StreamChunkEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from harnessweaver.core.messages import ModelRequest, ModelResponse, StreamChunk, ToolCall
from harnessweaver.core.outcomes import (
    Block,
    Continue,
    Escalate,
    Outcome,
    OutcomeKind,
    Retry,
    Suspend,
)
from harnessweaver.core.ports import (
    ModelProvider,
    StreamingModelProvider,
    ToolBackend,
    ToolDescription,
)
from harnessweaver.core.retrieval import ContextItem
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest
from harnessweaver.core.state import Grant, call_digest, output_digest
from harnessweaver.core.tools import ToolInfo, ToolResult
from harnessweaver.core.trace import RunTrace

__all__ = [
    "MODEL_RETRIES",
    "SUSPENDABLE_HOOKS",
    "ModelAccess",
    "NoTools",
    "PendingApproval",
    "PromptSource",
    "RunContext",
    "TaskInfo",
    "current_run",
]

_log = logging.getLogger("harnessweaver.run")

_CURRENT: ContextVar["RunContext | None"] = ContextVar("harnessweaver_run", default=None)

MODEL_RETRIES = 1
"""How many times a ``Retry`` at ``model.after`` may re-ask the model."""

SUSPENDABLE_HOOKS = frozenset({HookPoint.TOOL_BEFORE, HookPoint.OUTPUT_BEFORE})
"""Where ``Suspend`` pauses for approval. Elsewhere it escalates (DESIGNS No. 18)."""


def current_run() -> "RunContext | None":
    """The run active in this task, for adapters and built-in middleware."""
    return _CURRENT.get()


class PromptSource(Protocol):
    """Renders versioned prompts (ADR-0013)."""

    async def render(self, ref: str, variables: Mapping[str, Any]) -> str: ...


@dataclass(frozen=True, slots=True)
class ModelAccess:
    """How a run reaches models: the provider, aliases and prices (DESIGNS No. 16)."""

    provider: ModelProvider | None = None
    default_alias: str | None = None
    aliases: Mapping[str, str] = field(default_factory=dict[str, str])
    allowed_aliases: frozenset[str] | None = None
    prices: PriceLookup | None = None


@dataclass(frozen=True, slots=True)
class TaskInfo:
    """The parts of a task a runner needs, without the spec types."""

    name: str
    version: str = "1.0.0"
    model: str | None = None
    prompt: str | None = None
    tools: tuple[str, ...] = ()
    input_type: type[Any] | None = None
    output_type: type[Any] | None = None
    """A Pydantic model, ``str``, or ``None`` for whatever the model returns."""
    max_repairs: int = 1
    on_failure: str = "block"


class NoTools:
    """The tool backend when none is configured: every tool is unknown."""

    def describe(self, name: str) -> ToolDescription | None:
        return None

    async def execute(self, call: ToolCall, env: Envelope) -> ToolResult:  # pragma: no cover
        raise SpecError(f"no tool backend is configured for {call.name!r}")


@dataclass(frozen=True, slots=True)
class PendingApproval:
    """What a ``Suspend`` paused on, so the harness can ask a human and resume."""

    hook: HookPoint
    reason: str
    approver_role: str | None
    digest: str
    call: ToolCall | None = None
    tool: ToolInfo | None = None


class RunContext:
    """The state of one run and its governed operations.

    Args:
        envelope: The run's envelope; its clock is the run's clock.
        bus: The harness's hook bus.
        trace: Where every outcome is recorded (R13).
        meter: The run's budget meter.
        models: Model access.
        tools: Tool backend.
        task: The task being run, if any.
        prompts: Where prompts come from.
        grants: Approvals already given (when resuming).
        on_chunk: Called with each streamed chunk after ``stream.chunk``.
        harness: The owning harness, for runners that build sessions.
        can_suspend: Whether ``Suspend`` may pause this run. Standalone sessions
            can't be resumed, so there it escalates instead (DESIGNS No. 15).
    """

    def __init__(
        self,
        *,
        envelope: Envelope,
        bus: HookBus,
        trace: RunTrace,
        meter: BudgetMeter,
        models: ModelAccess | None = None,
        tools: ToolBackend | None = None,
        task: TaskInfo | None = None,
        prompts: PromptSource | None = None,
        grants: Iterable[Grant] = (),
        on_chunk: Callable[[StreamChunk], None] | None = None,
        harness: object = None,
        can_suspend: bool = True,
    ) -> None:
        self._envelope = envelope
        self.bus = bus
        self.trace = trace
        self.meter = meter
        self.models = models or ModelAccess()
        self.tools: ToolBackend = tools or NoTools()
        self.task = task
        self.prompts = prompts
        self.grants: list[Grant] = list(grants)
        self.on_chunk = on_chunk
        self.harness = harness
        self.can_suspend = can_suspend
        self.pending: PendingApproval | None = None
        self.resume_point: dict[str, JsonValue] = {}
        self.output: JsonValue = None

    # --- envelope ---------------------------------------------------------------------------

    @property
    def envelope(self) -> Envelope:
        return self._envelope

    @property
    def clock(self) -> Clock:
        return self._envelope.clock

    @property
    def run_id(self) -> str:
        return self._envelope.run_id

    @property
    def task_name(self) -> str | None:
        return self.task.name if self.task is not None else None

    def _refresh_budget(self) -> None:
        self._envelope = self._envelope.model_copy(
            update={"budget": self.meter.remaining(self._envelope.remaining())}
        )

    def mark_untrusted(self, source: str) -> None:
        """Record that untrusted content entered the run (S3)."""
        self._envelope = self._envelope.with_labels(self._envelope.labels.mark_untrusted(source))

    def mark_private(self, source: str) -> None:
        """Record that the run holds private data (S3)."""
        self._envelope = self._envelope.with_labels(self._envelope.labels.mark_private(source))

    @contextlib.contextmanager
    def activate(self) -> Generator["RunContext"]:
        """Make this the current run for the enclosed code (see :func:`current_run`)."""
        token = _CURRENT.set(self)
        try:
            yield self
        finally:
            _CURRENT.reset(token)

    def set_resume_point(self, state: Mapping[str, JsonValue]) -> None:
        """Tell the harness where to resume if the next step suspends."""
        self.resume_point = dict(state)

    def time_left(self) -> timedelta | None:
        return self._envelope.remaining()

    # --- hooks ------------------------------------------------------------------------------

    def _check_deadline(self) -> None:
        left = self._envelope.remaining()
        if left is not None and left <= timedelta(0):
            raise DeadlineExceeded("the run passed its deadline")

    async def emit[E](
        self, hook: HookPoint, event: E, *, source: str = "harness", check_deadline: bool = True
    ) -> HookResult[E]:
        """Fire ``hook`` on the bus with the current envelope. Doesn't raise for outcomes.

        Raises:
            DeadlineExceeded: If the run is past its deadline (unless told not to check).
        """
        if check_deadline:
            self._check_deadline()
        return await self.bus.emit(
            hook, event, self._envelope, self.trace, task=self.task_name, source=source
        )

    def interrupt(self, hook: HookPoint, outcome: Outcome) -> RunInterrupted:
        """The error a halting outcome becomes (ADR-0020)."""
        if isinstance(outcome, Retry):
            outcome = Block(
                reason=f"Retry isn't supported at {hook.value}: {outcome.reason}",
                code="retry_not_supported",
            )
        if isinstance(outcome, Suspend) and (hook not in SUSPENDABLE_HOOKS or not self.can_suspend):
            where = hook.value if self.can_suspend else "a standalone session"
            self.trace.note("harness", f"can't suspend at {where}; escalating", hook=hook)
            outcome = Escalate(reason=outcome.reason, to=outcome.approver_role)
        if isinstance(outcome, Block):
            return RunBlocked(outcome.reason, hook=hook.value, code=outcome.code)
        if isinstance(outcome, Escalate):
            return RunEscalated(outcome.reason, hook=hook.value, to=outcome.to)
        if isinstance(outcome, Suspend):
            return RunSuspended(
                outcome.reason, hook=hook.value, approver_role=outcome.approver_role
            )
        raise AssertionError(f"{outcome.kind} doesn't halt a run")

    def halt_on(self, result: HookResult[Any], *, allow_retry: bool = False) -> None:
        """Raise the interrupt for a halting outcome; return for ``Continue``."""
        outcome = result.outcome
        if isinstance(outcome, Continue) or (allow_retry and isinstance(outcome, Retry)):
            return
        raise self.interrupt(result.hook, outcome)

    def _budget_stop(self, hook: HookPoint, limit: str) -> NoReturn:
        block = breach_block(limit, self.meter.limits)  # pyright: ignore[reportArgumentType]
        self.trace.note(
            "harness.budget",
            block.reason,
            hook=hook,
            code=block.code,
            outcome=OutcomeKind(block.kind),
        )
        raise RunBlocked(block.reason, hook=hook.value, code=block.code, limit=limit)

    def _grant(self, hook: HookPoint, digest: str) -> Grant | None:
        return next((g for g in self.grants if g.hook == hook.value and g.digest == digest), None)

    # --- input, routing, context ------------------------------------------------------------

    async def check_input(self, value: JsonValue) -> JsonValue:
        """Fire ``input.before``; return the (possibly redacted) input."""
        result = await self.emit(HookPoint.INPUT_BEFORE, InputEvent(input=value))
        self.halt_on(result)
        return result.event.input

    async def decide(self, request: DecisionRequest, *, default: str | None = None) -> Decision:
        """Fire ``route.decide``. Without an answer, use ``default`` or abstain."""
        result = await self.emit(HookPoint.ROUTE_DECIDE, RouteEvent(request=request))
        self.halt_on(result)
        decision = result.event.decision
        if decision is None:
            decision = (
                Decision.default(default, reason="no stage decided")
                if default is not None
                else Decision.abstain(reason="no stage decided")
            )
        details: dict[str, JsonValue] = {"router": request.router, "kind": decision.kind.value}
        if decision.choice is not None:
            details["choice"] = decision.choice
        if decision.confidence is not None:
            details["confidence"] = decision.confidence
        if decision.stage is not None:
            details["stage"] = decision.stage
        self.trace.note(
            "harness.decision",
            decision.reason or decision.kind.value,
            hook=HookPoint.ROUTE_DECIDE,
            details=details,
        )
        return decision

    async def context_after(
        self, source: str, items: Iterable[ContextItem], *, query: str | None = None
    ) -> tuple[ContextItem, ...]:
        """Fire ``context.after`` on retrieved items; label the run if any are untrusted."""
        event = ContextEvent(source=source, query=query, items=tuple(items))
        result = await self.emit(HookPoint.CONTEXT_AFTER, event)
        self.halt_on(result)
        kept = result.event.items
        if any(item.untrusted for item in kept):
            self.mark_untrusted(f"context:{source}")
        return kept

    # --- models -----------------------------------------------------------------------------

    def _resolve_model(self, request: ModelRequest) -> ModelRequest:
        access = self.models
        allowed = access.allowed_aliases
        if request.model is not None and request.alias is None:
            if allowed is not None:
                permitted = {access.aliases.get(a, a) for a in allowed}
                if request.model not in permitted:
                    self._model_not_allowed(f"model {request.model!r} isn't allowed")
            return request
        alias = request.alias or (self.task.model if self.task else None) or access.default_alias
        if alias is None:
            return request
        if allowed is not None and alias not in allowed:
            self._model_not_allowed(f"model alias {alias!r} isn't in models.allowed_aliases")
        return request.model_copy(
            update={"alias": alias, "model": access.aliases.get(alias, alias)}
        )

    def _model_not_allowed(self, reason: str) -> NoReturn:
        self.trace.note(
            "harness.models", reason, hook=HookPoint.MODEL_BEFORE, code="model_not_allowed"
        )
        raise RunBlocked(reason, hook=HookPoint.MODEL_BEFORE.value, code="model_not_allowed")

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Make one governed model call: ``model.before``, the provider, ``model.after``.

        Budgets are checked before the call and after it. A ``Retry`` at
        ``model.after`` re-asks the model up to :data:`MODEL_RETRIES` times.

        Raises:
            RunInterrupted: When a hook or a budget halts the run.
            ProviderError: When the provider fails.
        """
        request = self._resolve_model(request)
        retries = 0
        while True:
            limit = self.meter.check_model_call(request)
            if limit is not None:
                self._budget_stop(HookPoint.MODEL_BEFORE, limit)
            before = await self.emit(HookPoint.MODEL_BEFORE, ModelRequestEvent(request=request))
            self.halt_on(before)
            sent = before.event.request
            if sent.alias != request.alias:
                sent = self._resolve_model(sent.model_copy(update={"model": None}))
            self.meter.start_model_call()
            response = await self._call_provider(sent)
            cost, source = resolve_cost(response, sent, self.models.prices)
            over = self.meter.record_model_call(response.usage, cost)
            usage: dict[str, JsonValue] = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "cost_source": source,
            }
            if cost is not None:
                usage["cost_usd"] = cost
            self.trace.note(
                "harness.budget", "model usage", hook=HookPoint.MODEL_AFTER, details=usage
            )
            self._refresh_budget()
            after = await self.emit(
                HookPoint.MODEL_AFTER, ModelResponseEvent(request=sent, response=response)
            )
            if over is not None:
                self._budget_stop(HookPoint.MODEL_AFTER, over)
            if isinstance(after.outcome, Retry) and retries < MODEL_RETRIES:
                retries += 1
                self.trace.note(
                    "harness",
                    f"re-asking the model: {after.outcome.reason}",
                    hook=HookPoint.MODEL_AFTER,
                )
                request = sent
                continue
            if isinstance(after.outcome, Retry):
                outcome = Block(
                    reason=f"model retries exhausted: {after.outcome.reason}",
                    code="retry_exhausted",
                )
                raise self.interrupt(HookPoint.MODEL_AFTER, outcome)
            self.halt_on(after)
            return after.event.response

    async def _call_provider(self, request: ModelRequest) -> ModelResponse:
        provider = self.models.provider
        if provider is None:
            raise SpecError("no model provider is configured; set models.provider")
        try:
            if request.stream and isinstance(provider, StreamingModelProvider):
                return await self._stream(provider, request)
            return await provider.generate(request, self._envelope)
        except HarnessError:
            raise
        except Exception as exc:
            raise ProviderError(f"the model provider failed ({type(exc).__name__})") from exc

    async def _stream(
        self, provider: StreamingModelProvider, request: ModelRequest
    ) -> ModelResponse:
        text = ""
        final: ModelResponse | None = None
        stream = provider.stream(request, self._envelope)
        try:
            async for item in stream:
                if isinstance(item, ModelResponse):
                    final = item
                    continue
                event = StreamChunkEvent(request=request, chunk=item, text_so_far=text)
                result = await self.emit(HookPoint.STREAM_CHUNK, event)
                self.halt_on(result)  # a Block cuts the stream here
                chunk = result.event.chunk
                text += chunk.delta
                if self.on_chunk is not None:
                    self.on_chunk(chunk)
        finally:
            closer = getattr(stream, "aclose", None)
            if closer is not None:
                await closer()
        if final is None:
            return ModelResponse(text=text)
        return final.model_copy(update={"text": text})

    # --- tools ------------------------------------------------------------------------------

    async def call_tool(self, call: ToolCall) -> ToolResult:
        """Make one governed tool call: ``tool.before``, the tool, ``tool.after``.

        A call a human already approved carries the approval into ``tool.before``,
        with any edited arguments applied (DESIGNS No. 18).

        Raises:
            RunInterrupted: When a hook or a budget halts the run.
        """
        description = self.tools.describe(call.name)
        if description is None:
            reason = f"tool {call.name!r} isn't registered"
            self.trace.note(
                "harness.tools", reason, hook=HookPoint.TOOL_BEFORE, code="tool_unknown"
            )
            raise RunBlocked(reason, hook=HookPoint.TOOL_BEFORE.value, code="tool_unknown")
        digest = call_digest(call)
        grant = self._grant(HookPoint.TOOL_BEFORE, digest)
        if grant is not None and grant.decision.edited_args is not None:
            call = call.model_copy(update={"arguments": grant.decision.edited_args})
        limit = self.meter.check_tool_call()
        if limit is not None:
            self._budget_stop(HookPoint.TOOL_BEFORE, limit)
        event = ToolCallEvent(
            call=call, tool=description.info, approval=grant.decision if grant else None
        )
        before = await self.emit(HookPoint.TOOL_BEFORE, event)
        if isinstance(before.outcome, Suspend):
            self.pending = PendingApproval(
                HookPoint.TOOL_BEFORE,
                before.outcome.reason,
                before.outcome.approver_role,
                digest,
                call=before.event.call,
                tool=description.info,
            )
        self.halt_on(before)
        call = before.event.call
        self.meter.start_tool_call()
        self._refresh_budget()
        try:
            result = await self.tools.execute(call, self._envelope)
        except Exception as exc:
            # The model sees that the tool failed, not why: the message may hold content (R9).
            self.trace.note(
                "harness.tools",
                f"tool {call.name} raised {type(exc).__name__}",
                hook=HookPoint.TOOL_AFTER,
                code="tool_error",
            )
            result = ToolResult(
                call_id=call.id, output={"error": type(exc).__name__}, is_error=True
            )
        after = await self.emit(
            HookPoint.TOOL_AFTER, ToolResultEvent(call=call, tool=description.info, result=result)
        )
        self.halt_on(after)
        final = after.event.result
        if final.untrusted:
            self.mark_untrusted(f"tool:{call.name}")
        if description.info.reads_private_data:
            self.mark_private(f"tool:{call.name}")
        return final

    def tool_specs(self, names: Iterable[str]) -> list[ToolDescription]:
        """Describe tools by name.

        Raises:
            SpecError: If one isn't registered.
        """
        found: list[ToolDescription] = []
        for name in names:
            description = self.tools.describe(name)
            if description is None:
                raise SpecError(f"tool {name!r} isn't registered")
            found.append(description)
        return found

    # --- output and approvals ---------------------------------------------------------------

    async def check_output(
        self, output: JsonValue, *, attempt: int = 0, schema_name: str | None = None
    ) -> HookResult[OutputEvent]:
        """Fire ``output.before``. ``Retry`` is returned for the caller to repair.

        Raises:
            RunInterrupted: For ``Block``, ``Escalate`` or ``Suspend``.
        """
        digest = output_digest(output)
        grant = self._grant(HookPoint.OUTPUT_BEFORE, digest)
        event = OutputEvent(
            output=output,
            attempt=attempt,
            schema_name=schema_name,
            approval=grant.decision if grant else None,
        )
        result = await self.emit(HookPoint.OUTPUT_BEFORE, event)
        if isinstance(result.outcome, Suspend):
            self.pending = PendingApproval(
                HookPoint.OUTPUT_BEFORE,
                result.outcome.reason,
                result.outcome.approver_role,
                digest,
            )
        self.halt_on(result, allow_retry=True)
        return result

    async def approval_resolved(self, request: ApprovalRequest, decision: ApprovalDecision) -> None:
        """Fire ``approval.resolved``; a halting outcome ends the run."""
        result = await self.emit(
            HookPoint.APPROVAL_RESOLVED, ApprovalResolvedEvent(request=request, decision=decision)
        )
        self.halt_on(result)
