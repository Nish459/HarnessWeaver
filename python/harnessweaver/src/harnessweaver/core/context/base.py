"""The state of one run and the hook plumbing its governed operations share."""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import timedelta
from typing import Any, Literal, NoReturn

from pydantic import JsonValue

from harnessweaver.core.budgets import BudgetMeter, breach_block
from harnessweaver.core.bus import HookBus, HookResult
from harnessweaver.core.context.access import (
    SUSPENDABLE_HOOKS,
    ModelAccess,
    NoTools,
    PendingApproval,
    PromptSource,
    TaskInfo,
)
from harnessweaver.core.envelope import Clock, Envelope
from harnessweaver.core.errors import (
    DeadlineExceeded,
    RunBlocked,
    RunEscalated,
    RunInterrupted,
    RunSuspended,
)
from harnessweaver.core.hooks import (
    HookPoint,
)
from harnessweaver.core.messages import StreamChunk
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
    ContextGovernor,
    Memory,
    PolicyEngine,
    ToolBackend,
    ToolGovernor,
)
from harnessweaver.core.state import Grant, RecordedCall
from harnessweaver.core.telemetry import Telemetry
from harnessweaver.core.trace import RunTrace

__all__ = ["RunContextBase"]


class RunContextBase:
    """A run's envelope, trace, meter and grants, and how hooks fire (ADR-0020)."""

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
        telemetry: Telemetry | None = None,
        governor: ToolGovernor | None = None,
        policy: PolicyEngine | None = None,
        context: ContextGovernor | None = None,
        memory: Memory | None = None,
        memory_ttl: timedelta | None = None,
        context_ids: Iterable[str] = (),
        recorder: Callable[[RecordedCall], Awaitable[None]] | None = None,
        recorded: int = 0,
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
        self.telemetry = telemetry
        self.governor = governor
        self.policy = policy
        self.context = context
        self.memory = memory
        self.memory_ttl = memory_ttl
        self.context_ids: set[str] = set(context_ids)
        """Ids of the context items this run kept, for ``grounded.citations``."""
        self.recorder = recorder
        """Keeps what the run gets from outside, for replay (``state.record``)."""
        self._recorded = recorded
        self.input: JsonValue = None
        """The run's input after ``input.before``, for validation rules."""
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

    async def record(
        self, kind: Literal["model", "tool", "approval"], digest: str, **fields: Any
    ) -> None:
        """Keep a model answer, tool result or approval when the spec records runs
        (``state.record: true``, ADR-0035)."""
        if self.recorder is None:
            return
        call = RecordedCall(
            run_id=self.run_id, seq=self._recorded, kind=kind, digest=digest, **fields
        )
        self._recorded += 1
        await self.recorder(call)

    def mark_untrusted(self, source: str) -> None:
        """Record that untrusted content entered the run (S3)."""
        self._envelope = self._envelope.with_labels(self._envelope.labels.mark_untrusted(source))

    def mark_private(self, source: str) -> None:
        """Record that the run holds private data (S3)."""
        self._envelope = self._envelope.with_labels(self._envelope.labels.mark_private(source))

    def set_trace_id(self, trace_id: str | None) -> None:
        """Correlate the envelope with the run's OpenTelemetry trace."""
        if trace_id is not None and self._envelope.trace_id is None:
            self._envelope = self._envelope.model_copy(update={"trace_id": trace_id})

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
