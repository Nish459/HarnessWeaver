"""The error taxonomy.

Only these errors cross a public boundary (RULES C5). Every error has a stable
``code`` that is part of the wire contract (see :class:`ErrorInfo`), so other
languages and the sidecar report failures the same way.

Messages must never contain raw prompts, outputs or tool arguments (R9).
"""

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from pydantic import ValidationError as _PydanticValidationError

__all__ = [
    "BoundViolation",
    "BudgetExceeded",
    "DeadlineExceeded",
    "ErrorCode",
    "ErrorInfo",
    "ExpressionError",
    "ExpressionEvalError",
    "ExpressionSyntaxError",
    "HarnessError",
    "IncompatibleContract",
    "InternalError",
    "LevelTooLow",
    "LockViolation",
    "PluginConflict",
    "PluginNotAllowed",
    "PolicyDenied",
    "ProviderError",
    "SpecError",
    "ToolError",
    "UnknownProvider",
    "UnreachableHook",
    "ValidationFailed",
    "classify",
    "from_known",
]


class ErrorCode(StrEnum):
    """Stable, language-neutral error codes."""

    BUDGET_EXCEEDED = "budget_exceeded"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    POLICY_DENIED = "policy_denied"
    VALIDATION_FAILED = "validation_failed"
    PROVIDER_ERROR = "provider_error"
    TOOL_ERROR = "tool_error"
    EXPRESSION_ERROR = "expression_error"
    SPEC_INVALID = "spec_invalid"
    INTERNAL = "internal"


class ErrorInfo(BaseModel):
    """The serializable form of an error, as carried by hook events and the wire API."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ErrorCode
    type: str = Field(description="The error class name, e.g. 'LockViolation'.")
    message: str
    retryable: bool = False
    details: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class HarnessError(Exception):
    """Base class for every error HarnessWeaver raises across a public boundary."""

    code: ClassVar[ErrorCode] = ErrorCode.INTERNAL
    retryable: ClassVar[bool] = False

    def __init__(self, message: str, **details: JsonValue) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, JsonValue] = details

    def to_info(self) -> ErrorInfo:
        """Return the serializable form of this error."""
        return ErrorInfo(
            code=self.code,
            type=type(self).__name__,
            message=self.message,
            retryable=self.retryable,
            details=self.details,
        )


class BudgetExceeded(HarnessError):
    """A run would exceed, or has exceeded, one of its budget limits."""

    code = ErrorCode.BUDGET_EXCEEDED


class DeadlineExceeded(HarnessError):
    """A run passed its deadline."""

    code = ErrorCode.DEADLINE_EXCEEDED


class PolicyDenied(HarnessError):
    """A deterministic policy refused an action."""

    code = ErrorCode.POLICY_DENIED


class ValidationFailed(HarnessError):
    """Input or output failed validation and could not be repaired."""

    code = ErrorCode.VALIDATION_FAILED


class ProviderError(HarnessError):
    """A model or other upstream provider failed. Usually worth retrying."""

    code = ErrorCode.PROVIDER_ERROR
    retryable = True


class ToolError(HarnessError):
    """A tool failed while executing."""

    code = ErrorCode.TOOL_ERROR


class InternalError(HarnessError):
    """A bug or an unexpected failure inside HarnessWeaver or a plugin."""

    code = ErrorCode.INTERNAL


class ExpressionError(HarnessError):
    """A cel-lite expression could not be compiled or evaluated."""

    code = ErrorCode.EXPRESSION_ERROR


class ExpressionSyntaxError(ExpressionError):
    """A cel-lite expression is malformed or calls something that doesn't exist."""


class ExpressionEvalError(ExpressionError):
    """A cel-lite expression failed at evaluation time (missing key, type mismatch, ...)."""


class SpecError(HarnessError):
    """A spec is invalid. Raised when a harness loads, never at run time."""

    code = ErrorCode.SPEC_INVALID


class LockViolation(SpecError):
    """A later layer changed a value the org baseline locked (R1)."""


class BoundViolation(SpecError):
    """A value is outside the bounds the org baseline set (R10)."""


class LevelTooLow(SpecError):
    """The app's effective spec is below the adoption level its risk tier requires."""


class UnreachableHook(SpecError):
    """A runner or adapter can't reach a hook point the baseline needs (R4)."""


class IncompatibleContract(SpecError):
    """A plugin was built for a contract range this core doesn't support (V5)."""


class UnknownProvider(SpecError):
    """A spec names a provider, runner or plugin that isn't installed (R4)."""


class PluginConflict(SpecError):
    """Two installed plugins claim the same namespace."""


class PluginNotAllowed(SpecError):
    """A spec uses a plugin that the org baseline's ``plugins.allow`` list excludes."""


def from_known(exc: BaseException) -> HarnessError | None:
    """Translate a well-known exception into the taxonomy, or return ``None``.

    Adapters call this first and fall back to :class:`InternalError`.
    """
    if isinstance(exc, HarnessError):
        return exc
    if isinstance(exc, TimeoutError):
        return DeadlineExceeded("the operation timed out")
    if isinstance(exc, _PydanticValidationError):
        # Only error locations and types; the input values may hold raw content (R9).
        return ValidationFailed(
            f"{exc.error_count()} validation error(s) for {exc.title}",
            errors=[{"loc": [str(p) for p in e["loc"]], "type": e["type"]} for e in exc.errors()],
        )
    return None


def classify(exc: BaseException) -> HarnessError:
    """Translate any exception into the taxonomy, defaulting to :class:`InternalError`."""
    known = from_known(exc)
    if known is not None:
        return known
    return InternalError(f"unexpected {type(exc).__name__}")
