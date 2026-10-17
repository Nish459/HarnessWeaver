"""RunTrace: the framework-neutral record of every decision in a run (R13, ADR-0010).

Every middleware outcome, middleware failure, budget check and status change is
recorded here with its reason. The trace powers ``assert_trace`` in tests and
``harnessweaver replay``, and it is always kept on the run's result.

Trace events never hold raw prompts, outputs or tool arguments (R9). They carry
names, outcome kinds, reasons and codes, and a flag when a payload was modified.
"""

from collections.abc import Callable, Iterator
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from harnessweaver.core.envelope import Clock
from harnessweaver.core.hooks import Band, HookPoint
from harnessweaver.core.outcomes import Block, Continue, Outcome, OutcomeKind

__all__ = ["RunTrace", "TraceEvent", "TraceKind"]


class TraceKind(StrEnum):
    """What a trace event records."""

    HOOK = "hook"
    """A hook point fired. ``outcome`` is the combined result of its middleware."""
    OUTCOME = "outcome"
    """A middleware answered a hook event."""
    FAILURE = "failure"
    """A middleware raised or timed out; its fail mode decided the outcome."""
    NOTE = "note"
    """A framework event: a budget check, a status change, a decision, a shadow guard."""


class TraceEvent(BaseModel):
    """One entry in a :class:`RunTrace`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int = Field(ge=0, description="Position in the run's trace, from 0.")
    at: AwareDatetime
    kind: TraceKind
    source: str = Field(min_length=1, description="Middleware name, or 'harness.<area>'.")
    hook: HookPoint | None = None
    band: Band | None = None
    outcome: OutcomeKind | None = None
    modified: bool = Field(default=False, description="The middleware changed the payload.")
    reason: str | None = None
    code: str | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class RunTrace:
    """An append-only list of :class:`TraceEvent` for one run.

    ``on_event`` is called with each new event, so a harness can stream them live.
    """

    def __init__(
        self,
        clock: Clock,
        *,
        events: tuple[TraceEvent, ...] = (),
        on_event: Callable[[TraceEvent], None] | None = None,
    ) -> None:
        self._clock = clock
        self._events: list[TraceEvent] = list(events)
        self._on_event = on_event

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    def __iter__(self) -> Iterator[TraceEvent]:
        return iter(tuple(self._events))

    def __len__(self) -> int:
        return len(self._events)

    def _append(self, **fields: object) -> TraceEvent:
        event = TraceEvent.model_validate(
            {"seq": len(self._events), "at": self._clock.now(), **fields}
        )
        self._events.append(event)
        if self._on_event is not None:
            self._on_event(event)
        return event

    def hook(
        self, hook: HookPoint, source: str, outcome: Outcome, *, middleware: int
    ) -> TraceEvent:
        """Record that ``hook`` fired, from ``source``, and the combined outcome."""
        return self._append(
            kind=TraceKind.HOOK,
            source=source,
            hook=hook,
            outcome=OutcomeKind(outcome.kind),
            modified=isinstance(outcome, Continue) and outcome.modified is not None,
            reason=_reason(outcome),
            code=outcome.code if isinstance(outcome, Block) else None,
            details={"middleware": middleware},
        )

    def outcome(
        self, hook: HookPoint, source: str, band: Band | None, outcome: Outcome
    ) -> TraceEvent:
        """Record a middleware's answer to a hook event."""
        return self._append(
            kind=TraceKind.OUTCOME,
            source=source,
            hook=hook,
            band=band,
            outcome=OutcomeKind(outcome.kind),
            modified=isinstance(outcome, Continue) and outcome.modified is not None,
            reason=_reason(outcome),
            code=outcome.code if isinstance(outcome, Block) else None,
        )

    def failure(
        self,
        hook: HookPoint,
        source: str,
        band: Band | None,
        outcome: Outcome,
        *,
        error_type: str,
        timed_out: bool,
    ) -> TraceEvent:
        """Record a middleware that raised or timed out, and the outcome its fail mode chose.

        Only the exception's type is recorded: its message may hold raw content (R9).
        """
        return self._append(
            kind=TraceKind.FAILURE,
            source=source,
            hook=hook,
            band=band,
            outcome=OutcomeKind(outcome.kind),
            reason=_reason(outcome),
            code=outcome.code if isinstance(outcome, Block) else None,
            details={"error_type": error_type, "timed_out": timed_out},
        )

    def note(
        self,
        source: str,
        reason: str,
        *,
        hook: HookPoint | None = None,
        code: str | None = None,
        outcome: OutcomeKind | None = None,
        details: dict[str, JsonValue] | None = None,
    ) -> TraceEvent:
        """Record a framework event, such as a budget check or a status change."""
        return self._append(
            kind=TraceKind.NOTE,
            source=source,
            hook=hook,
            outcome=outcome,
            reason=reason,
            code=code,
            details=details or {},
        )

    def for_hook(self, hook: HookPoint) -> list[TraceEvent]:
        """Events recorded for one hook point, in order."""
        return [event for event in self._events if event.hook is hook]

    def hooks_fired(self) -> list[HookPoint]:
        """Hook points that appear in the trace, in the order they first appear."""
        seen: list[HookPoint] = []
        for event in self._events:
            if event.hook is not None and event.hook not in seen:
                seen.append(event.hook)
        return seen


def _reason(outcome: Outcome) -> str | None:
    if isinstance(outcome, Continue):
        return outcome.note
    return outcome.reason
