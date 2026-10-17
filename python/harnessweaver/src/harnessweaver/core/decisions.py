"""Routing decisions and policy effects.

A :class:`Decision` answers "which option?" and may be probabilistic. A
:class:`PolicyEffect` answers "may this happen?" and must come from a
deterministic engine. Probabilistic checks may only :func:`tighten` it (R3).
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

__all__ = ["Decision", "DecisionKind", "DecisionRequest", "PolicyEffect", "tighten"]


class DecisionRequest(BaseModel):
    """A question for a router: pick one of ``options`` for ``text`` and ``state``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    router: str = Field(min_length=1)
    text: str | None = None
    options: tuple[str, ...] = ()
    state: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class DecisionKind(StrEnum):
    """How a decision was reached."""

    EXACT = "exact"
    PROBABILISTIC = "probabilistic"
    ABSTAIN = "abstain"
    DEFAULT = "default"


class Decision(BaseModel):
    """A router's answer, with the stage and reason that produced it (R13)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: DecisionKind
    choice: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = None
    stage: str | None = Field(default=None, description="The cascade stage that answered.")

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if self.kind is DecisionKind.ABSTAIN:
            if self.choice is not None:
                raise ValueError("an abstaining decision has no choice")
        elif self.choice is None:
            raise ValueError(f"a {self.kind} decision needs a choice")
        if self.kind is DecisionKind.PROBABILISTIC and self.confidence is None:
            raise ValueError("a probabilistic decision needs a confidence")
        return self

    @classmethod
    def exact(cls, choice: str, *, reason: str | None = None) -> Self:
        return cls(kind=DecisionKind.EXACT, choice=choice, confidence=1.0, reason=reason)

    @classmethod
    def probabilistic(cls, choice: str, confidence: float, *, reason: str | None = None) -> Self:
        return cls(
            kind=DecisionKind.PROBABILISTIC, choice=choice, confidence=confidence, reason=reason
        )

    @classmethod
    def abstain(cls, *, reason: str | None = None) -> Self:
        return cls(kind=DecisionKind.ABSTAIN, reason=reason)

    @classmethod
    def default(cls, choice: str, *, reason: str | None = None) -> Self:
        return cls(kind=DecisionKind.DEFAULT, choice=choice, reason=reason)


class PolicyEffect(StrEnum):
    """The outcome of a policy check, from most to least permissive."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"

    @property
    def rank(self) -> int:
        return _EFFECT_RANK[self]


_EFFECT_RANK = {PolicyEffect.ALLOW: 0, PolicyEffect.REQUIRE_APPROVAL: 1, PolicyEffect.DENY: 2}


def tighten(current: PolicyEffect, proposed: PolicyEffect) -> PolicyEffect:
    """Combine a policy effect with a check that may only make it stricter (R3).

    A judge or classifier can turn ``allow`` into ``require_approval`` or
    ``deny``, but never the other way round.
    """
    return proposed if proposed.rank > current.rank else current
