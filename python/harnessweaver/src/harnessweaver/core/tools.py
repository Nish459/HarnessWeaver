"""Tool contracts: what ``tool.before`` / ``tool.after`` carry, the governor's verdict, and
what a ``Sandbox`` runs (DESIGNS No. 17)."""

from datetime import timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from harnessweaver.core.durations import Duration

__all__ = [
    "Risk",
    "SandboxLimits",
    "SandboxResult",
    "SideEffect",
    "ToolInfo",
    "ToolResult",
    "ToolVerdict",
]


class SideEffect(StrEnum):
    """What a tool changes when it runs."""

    NONE = "none"
    READ = "read"
    WRITE_INTERNAL = "write_internal"
    WRITE_EXTERNAL = "write_external"
    DESTRUCTIVE = "destructive"


class Risk(StrEnum):
    """How much harm a misused call could do."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolInfo(BaseModel):
    """The parts of a tool manifest that policies and middleware decide on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    version: str | None = None
    side_effect: SideEffect = SideEffect.NONE
    risk: Risk = Risk.LOW
    egress: tuple[str, ...] = Field(default=(), description="Hosts the tool may reach.")
    data_access: tuple[str, ...] = Field(default=(), description="Data it reads, e.g. 'pii:x'.")
    scopes: tuple[str, ...] = ()

    @property
    def reads_private_data(self) -> bool:
        return any(item.startswith("pii") for item in self.data_access)


class ToolResult(BaseModel):
    """What a tool returned. Output is untrusted unless the manifest says otherwise (S3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str = Field(min_length=1)
    output: JsonValue = None
    is_error: bool = False
    untrusted: bool = True
    truncated: bool = False


class ToolVerdict(BaseModel):
    """What the governor decided about one call, and at which of its steps (DESIGNS No. 17)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["allow", "require_approval", "block"]
    step: int = Field(ge=1, le=7, description="The governor step that decided.")
    code: str | None = Field(default=None, description="Why, for blocks and approvals.")
    reason: str
    approver_role: str | None = None


class SandboxLimits(BaseModel):
    """Limits for one sandboxed run (S4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout: Duration = timedelta(seconds=5)
    max_memory_mb: int = Field(default=64, gt=0)
    max_output_bytes: int = Field(default=100_000, gt=0, description="Printed output kept.")


class SandboxResult(BaseModel):
    """What sandboxed code produced: its last expression's value, its printed output, or
    the error it raised (``"TypeName: message"``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: JsonValue = None
    stdout: str = ""
    error: str | None = None
