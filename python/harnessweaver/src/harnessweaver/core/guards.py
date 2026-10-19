"""The result every guardrail returns, and its seven actions."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["Finding", "GuardAction", "GuardResult"]


class GuardAction(StrEnum):
    """What a guardrail wants done with the content it checked.

    The guardrails module maps actions onto hook outcomes (DESIGNS No. 9).
    """

    ALLOW = "allow"
    REDACT = "redact"
    REPAIR = "repair"
    ESCALATE = "escalate"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"
    LOG_ONLY = "log_only"


class Finding(BaseModel):
    """Something a guardrail found. Never holds the raw matched text (R9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str = Field(min_length=1, description="What was found, e.g. 'EMAIL' or 'aws_key'.")
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    score: float | None = None
    private: bool = Field(
        default=False,
        description="It's private data such as PII; finding it marks the run private (S3).",
    )


class GuardResult(BaseModel):
    """A guardrail's verdict on one piece of content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: GuardAction
    content: str | None = Field(default=None, description="Replacement content, for 'redact'.")
    reason: str | None = None
    findings: tuple[Finding, ...] = ()
    score: float | None = None

    @model_validator(mode="after")
    def _check_content(self) -> Self:
        if self.action is GuardAction.REDACT and self.content is None:
            raise ValueError("a redact result needs the redacted content")
        return self

    @classmethod
    def allow(cls) -> Self:
        return cls(action=GuardAction.ALLOW)

    @classmethod
    def redact(
        cls, content: str, *, findings: tuple[Finding, ...] = (), reason: str | None = None
    ) -> Self:
        return cls(action=GuardAction.REDACT, content=content, findings=findings, reason=reason)

    @classmethod
    def repair(cls, reason: str, *, findings: tuple[Finding, ...] = ()) -> Self:
        return cls(action=GuardAction.REPAIR, reason=reason, findings=findings)

    @classmethod
    def escalate(cls, reason: str, *, findings: tuple[Finding, ...] = ()) -> Self:
        return cls(action=GuardAction.ESCALATE, reason=reason, findings=findings)

    @classmethod
    def require_approval(cls, reason: str, *, findings: tuple[Finding, ...] = ()) -> Self:
        return cls(action=GuardAction.REQUIRE_APPROVAL, reason=reason, findings=findings)

    @classmethod
    def block(cls, reason: str, *, findings: tuple[Finding, ...] = ()) -> Self:
        return cls(action=GuardAction.BLOCK, reason=reason, findings=findings)
