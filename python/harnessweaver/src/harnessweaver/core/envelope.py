"""The envelope: the immutable context carried by every hook event.

It records who a run acts for, what it is doing, how much it may spend and
what data it has touched. The mutable state of a run lives in its run context,
which produces a new envelope whenever labels or budgets change.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PrivateAttr,
    field_validator,
)

from harnessweaver.core.durations import Duration, parse_duration
from harnessweaver.core.ids import new_id

__all__ = [
    "Budget",
    "Clock",
    "Envelope",
    "FakeClock",
    "Labels",
    "Principal",
    "SystemClock",
]


class Clock(ABC):
    """The source of time for everything that makes decisions (RULES C4)."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""

    def is_weekend(self) -> bool:
        """Return whether it is Saturday or Sunday (UTC)."""
        return self.now().weekday() >= 5


class SystemClock(Clock):
    """The real clock. All instances are the same clock, so they compare equal."""

    def now(self) -> datetime:
        return datetime.now(UTC)  # noqa: TID251 - the one sanctioned read of wall time (C4)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SystemClock)

    def __hash__(self) -> int:
        return hash(SystemClock)


class FakeClock(Clock):
    """A clock that only moves when told to. For tests (RULES T8).

    It starts on Monday 2026-01-05 09:00 UTC unless given a start time.
    """

    def __init__(self, start: datetime | None = None) -> None:
        start = start or datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
        if start.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware start time")
        self._now = start.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta | str | float) -> None:
        """Move the clock forward by a duration such as ``"5m"``."""
        self._now += parse_duration(delta)

    def set(self, moment: datetime) -> None:
        """Jump to a specific, timezone-aware moment."""
        if moment.tzinfo is None:
            raise ValueError("FakeClock needs timezone-aware times")
        self._now = moment.astimezone(UTC)


class Principal(BaseModel):
    """Who a run acts for."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    roles: tuple[str, ...] = ()
    attrs: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])

    def has_role(self, role: str) -> bool:
        """Return whether the principal holds ``role``."""
        return role in self.roles


class Labels(BaseModel):
    """What kind of data a run has touched. Drives the lethal-trifecta check (RULES S3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_class: str | None = Field(
        default=None, description="Classification of the run's data, e.g. 'confidential'."
    )
    untrusted_seen: bool = Field(
        default=False, description="Untrusted content (retrieved context, tool output) entered."
    )
    private_seen: bool = Field(
        default=False, description="Private data (e.g. PII) was read or found in the input."
    )
    sources: tuple[str, ...] = Field(
        default=(), description="Where untrusted or private data came from, in order."
    )

    def _with_source(self, source: str | None) -> tuple[str, ...]:
        if source is None or source in self.sources:
            return self.sources
        return (*self.sources, source)

    def mark_untrusted(self, source: str | None = None) -> Self:
        """Return labels recording that untrusted content entered the run."""
        return self.model_copy(
            update={"untrusted_seen": True, "sources": self._with_source(source)}
        )

    def mark_private(self, source: str | None = None) -> Self:
        """Return labels recording that the run holds private data."""
        return self.model_copy(update={"private_seen": True, "sources": self._with_source(source)})


class Budget(BaseModel):
    """Limits for one run. ``None`` means no limit at this layer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_tokens: int | None = Field(default=None, ge=0)
    max_model_calls: int | None = Field(default=None, ge=0)
    max_tool_calls: int | None = Field(default=None, ge=0)
    deadline: Duration | None = None

    def intersect(self, other: "Budget") -> "Budget":
        """Return the tightest combination of two budgets (each limit's minimum)."""

        def tighter[T: (float, int, timedelta)](a: T | None, b: T | None) -> T | None:
            if a is None:
                return b
            if b is None:
                return a
            return min(a, b)

        return Budget(
            max_usd=tighter(self.max_usd, other.max_usd),
            max_tokens=tighter(self.max_tokens, other.max_tokens),
            max_model_calls=tighter(self.max_model_calls, other.max_model_calls),
            max_tool_calls=tighter(self.max_tool_calls, other.max_tool_calls),
            deadline=tighter(self.deadline, other.deadline),
        )


class Envelope(BaseModel):
    """The immutable context every hook event carries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    parent_run_id: str | None = None
    tenant: str = Field(min_length=1)
    principal: Principal
    task: str | None = None
    task_version: str | None = None
    budget: Budget = Budget()
    deadline: AwareDatetime | None = None
    labels: Labels = Labels()
    idempotency_key: str | None = None
    trace_id: str | None = None
    attributes: dict[str, str] = Field(
        default_factory=dict[str, str], description="Free-form app tags, e.g. channel or region."
    )

    _clock: Clock = PrivateAttr(default_factory=SystemClock)

    @field_validator("principal", mode="before")
    @classmethod
    def _principal_from_id(cls, value: Any) -> Any:
        # Accept a bare principal id for convenience: principal="alice".
        return {"id": value} if isinstance(value, str) else value

    @property
    def clock(self) -> Clock:
        """The clock decisions should use. Not part of the serialized envelope."""
        return self._clock

    @classmethod
    def new(
        cls,
        *,
        tenant: str,
        principal: Principal | str,
        task: str | None = None,
        task_version: str | None = None,
        budget: Budget | None = None,
        clock: Clock | None = None,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> Self:
        """Build the envelope for a new run. The deadline comes from ``budget.deadline``."""
        clock = clock or SystemClock()
        budget = budget or Budget()
        deadline = clock.now() + budget.deadline if budget.deadline is not None else None
        envelope = cls(
            run_id=run_id or new_id("run"),
            parent_run_id=parent_run_id,
            tenant=tenant,
            principal=principal if isinstance(principal, Principal) else Principal(id=principal),
            task=task,
            task_version=task_version,
            budget=budget,
            deadline=deadline,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            attributes=attributes or {},
        )
        envelope._clock = clock
        return envelope

    def with_labels(self, labels: Labels) -> Self:
        """Return a copy with new labels (the clock is kept)."""
        return self.model_copy(update={"labels": labels})

    def with_clock(self, clock: Clock) -> Self:
        """Return a copy that uses ``clock``."""
        copy = self.model_copy()
        copy._clock = clock
        return copy

    def remaining(self) -> timedelta | None:
        """Time left before the deadline (never negative), or ``None`` without a deadline."""
        if self.deadline is None:
            return None
        return max(self.deadline - self._clock.now(), timedelta(0))
