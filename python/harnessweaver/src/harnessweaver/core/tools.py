"""Tool contracts carried by ``tool.before`` and ``tool.after`` events."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue

__all__ = ["Risk", "SideEffect", "ToolInfo", "ToolResult"]


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
