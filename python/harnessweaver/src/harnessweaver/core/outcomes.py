"""What a middleware returns, and how several answers to one event combine.

Severity, most to least: ``Block`` > ``Suspend`` > ``Escalate`` > ``Retry`` >
``Continue(modified)`` > ``Continue``. When several middleware answer the same
event, the most severe outcome wins (DESIGNS No. 8, fixtures suite ``outcomes``).
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Block",
    "Continue",
    "Escalate",
    "Outcome",
    "OutcomeKind",
    "Retry",
    "Suspend",
    "most_severe",
    "severity",
]


class OutcomeKind(StrEnum):
    CONTINUE = "continue"
    RETRY = "retry"
    ESCALATE = "escalate"
    SUSPEND = "suspend"
    BLOCK = "block"


class _Outcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Continue(_Outcome):
    """Proceed. With ``modified``, later middleware and the operation see the new payload."""

    kind: Literal["continue"] = "continue"
    modified: Any = Field(default=None, description="The replacement event payload, if any.")
    note: str | None = None


class Retry(_Outcome):
    """Redo the step, within the step's retry or repair budget."""

    kind: Literal["retry"] = "retry"
    reason: str


class Escalate(_Outcome):
    """Stop the automated path and hand the run to a human queue."""

    kind: Literal["escalate"] = "escalate"
    reason: str
    to: str | None = Field(default=None, description="The queue or role to hand off to.")


class Suspend(_Outcome):
    """Pause the run durably until an approver answers."""

    kind: Literal["suspend"] = "suspend"
    reason: str
    approver_role: str | None = None


class Block(_Outcome):
    """Refuse. The step never executes and the run ends ``blocked``."""

    kind: Literal["block"] = "block"
    reason: str
    code: str = "blocked"


Outcome = Annotated[Continue | Retry | Escalate | Suspend | Block, Field(discriminator="kind")]
"""Any middleware outcome."""

_SEVERITY: dict[str, int] = {"retry": 2, "escalate": 3, "suspend": 4, "block": 5}


def severity(outcome: Outcome) -> int:
    """Rank an outcome: ``Continue`` 0, ``Continue(modified)`` 1, ... ``Block`` 5."""
    if isinstance(outcome, Continue):
        return 0 if outcome.modified is None else 1
    return _SEVERITY[outcome.kind]


def most_severe(outcomes: Iterable[Outcome]) -> Outcome:
    """Return the most severe outcome; the earliest one wins a tie.

    An empty sequence means nobody objected, so the result is ``Continue()``.
    """
    best: Outcome = Continue()
    best_rank = -1
    for outcome in outcomes:
        rank = severity(outcome)
        if rank > best_rank:
            best, best_rank = outcome, rank
    return best
