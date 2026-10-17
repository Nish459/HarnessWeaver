"""Neutral model-call contracts (RULES R7).

These types describe a model request and response without any SDK's types.
Model plugins translate between them and their vendor's API.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

__all__ = [
    "Message",
    "ModelRequest",
    "ModelResponse",
    "Role",
    "StreamChunk",
    "ToolCall",
    "ToolSpec",
    "Usage",
]


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Role(StrEnum):
    """Who wrote a message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(_Contract):
    """A tool call proposed by a model."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class Message(_Contract):
    """One message in a model conversation."""

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = Field(default=None, description="Set on tool-result messages.")
    name: str | None = None

    @model_validator(mode="after")
    def _check_role_fields(self) -> Self:
        if self.tool_calls and self.role is not Role.ASSISTANT:
            raise ValueError("only assistant messages carry tool calls")
        if (self.role is Role.TOOL) != (self.tool_call_id is not None):
            raise ValueError("tool messages, and only tool messages, need a tool_call_id")
        return self

    @classmethod
    def system(cls, content: str) -> Self:
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> Self:
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: tuple[ToolCall, ...] = ()) -> Self:
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, tool_call_id: str, content: str) -> Self:
        return cls(role=Role.TOOL, content=content, tool_call_id=tool_call_id)


class ToolSpec(_Contract):
    """A tool as offered to a model."""

    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, JsonValue] = Field(
        default_factory=lambda: dict[str, JsonValue]({"type": "object"})
    )


class Usage(_Contract):
    """Token usage of one or more model calls."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


class ModelRequest(_Contract):
    """A request to a model, by alias or concrete model name."""

    alias: str | None = Field(default=None, description="Requested alias, e.g. 'fast'.")
    model: str | None = Field(default=None, description="Concrete model, once resolved.")
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    output_schema: dict[str, JsonValue] | None = Field(
        default=None, description="JSON Schema the final output must satisfy."
    )
    temperature: float | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, gt=0)
    stream: bool = False
    metadata: dict[str, str] = Field(default_factory=dict[str, str])


class ModelResponse(_Contract):
    """A model's answer."""

    model: str | None = None
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    output: JsonValue = Field(default=None, description="Parsed structured output, if any.")
    usage: Usage = Usage()
    cost_usd: float | None = Field(
        default=None, ge=0, description="Cost reported by the provider, if it reports one."
    )
    finish_reason: str | None = None


class StreamChunk(_Contract):
    """One piece of a streamed model response."""

    index: int = Field(ge=0)
    delta: str = ""
    finish_reason: str | None = None
