"""Pydantic AI messages as HarnessWeaver's neutral contracts, and back (R7).

Hook payloads only ever hold neutral ``hw.ModelRequest`` and ``hw.ModelResponse``
values. A request keeps, for each neutral message, where it came from in the
Pydantic AI history, so text that ``model.before`` middleware changed (a
redaction) can be written back into the request the model receives.
"""

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Literal

from pydantic import BaseModel, JsonValue, TypeAdapter
from pydantic_ai.messages import (
    InstructionPart,
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextContent,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserContent,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RequestUsage
from pydantic_core import to_jsonable_python

import harnessweaver as hw

__all__ = [
    "Where",
    "apply_request",
    "from_neutral",
    "patch_text",
    "to_json",
    "to_neutral",
    "to_request",
    "user_text",
]

type Where = tuple[int, int] | Literal["instructions"] | None
"""Where a neutral message came from: ``(message, part)`` in the history, the
instructions, or ``None`` for a model's own answers."""

_JSON = TypeAdapter[JsonValue](JsonValue)


def to_json(value: Any) -> JsonValue:
    """A JSON copy of ``value``; objects JSON can't hold are shown by their type name."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    plain = to_jsonable_python(value, fallback=lambda v: type(v).__name__)  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    return _JSON.validate_python(plain)


def user_text(content: str | Sequence[UserContent]) -> str:
    """A user prompt's text; images, audio and documents aren't part of the neutral view."""
    if isinstance(content, str):
        return content
    texts = [
        c if isinstance(c, str) else c.content for c in content if isinstance(c, str | TextContent)
    ]
    return "\n".join(texts)


def _arguments(part: ToolCallPart) -> dict[str, JsonValue]:
    found = to_json(part.args_as_dict())
    return found if isinstance(found, dict) else {}


def _request_part(part: ModelRequestPart) -> hw.Message | None:
    match part:
        case SystemPromptPart():
            return hw.Message.system(part.content)
        case UserPromptPart():
            return hw.Message.user(user_text(part.content))
        case ToolReturnPart():
            return hw.Message.tool(part.tool_call_id, part.model_response_str())
        case RetryPromptPart() if part.tool_name is None:
            return hw.Message.user(part.model_response())
        case RetryPromptPart():
            return hw.Message.tool(part.tool_call_id, part.model_response())
        case _:
            return None


def _instructions(messages: Sequence[ModelMessage], params: ModelRequestParameters) -> str | None:
    if params.instruction_parts:
        return InstructionPart.join(params.instruction_parts)
    for message in reversed(messages):
        if isinstance(message, ModelRequest) and message.instructions is not None:
            return message.instructions
    return None


def _messages(
    messages: Sequence[ModelMessage], instructions: str | None
) -> tuple[list[hw.Message], list[Where]]:
    out: list[hw.Message] = []
    where: list[Where] = []
    if instructions:
        out.append(hw.Message.system(instructions))
        where.append("instructions")
    for i, message in enumerate(messages):
        if isinstance(message, ModelRequest):
            for j, part in enumerate(message.parts):
                converted = _request_part(part)
                if converted is not None:
                    out.append(converted)
                    where.append((i, j))
            continue
        text = "".join(p.content for p in message.parts if isinstance(p, TextPart))
        calls = tuple(
            hw.ToolCall(id=p.tool_call_id, name=p.tool_name, arguments=_arguments(p))
            for p in message.parts
            if isinstance(p, ToolCallPart)
        )
        out.append(hw.Message.assistant(text, calls))
        where.append(None)
    return out, where


def _spec(tool: ToolDefinition) -> hw.ToolSpec:
    schema = to_json(tool.parameters_json_schema)
    return hw.ToolSpec(
        name=tool.name,
        description=tool.description or "",
        input_schema=schema if isinstance(schema, dict) else {"type": "object"},
    )


def _output_schema(
    params: ModelRequestParameters,
) -> tuple[dict[str, Any] | None, list[hw.ToolSpec]]:
    """The schema to ask for, or the output tools to offer when there are several."""
    mode, tools = params.output_mode, params.output_tools
    if mode in ("native", "prompted", "auto") and params.output_object is not None:
        return dict(params.output_object.json_schema), []
    if mode in ("tool", "auto") and len(tools) == 1:
        return dict(tools[0].parameters_json_schema), []
    return None, [_spec(t) for t in tools]


def to_request(
    messages: Sequence[ModelMessage],
    settings: ModelSettings | None,
    params: ModelRequestParameters,
) -> tuple[hw.ModelRequest, list[Where]]:
    """The neutral request for a Pydantic AI model request, and where each message came from."""
    neutral, where = _messages(messages, _instructions(messages, params))
    schema, output_tools = _output_schema(params)
    output_schema = to_json(schema) if schema is not None else None
    temperature = (settings or {}).get("temperature")
    max_tokens = (settings or {}).get("max_tokens")
    request = hw.ModelRequest(
        messages=tuple(neutral),
        tools=(*(_spec(t) for t in params.function_tools), *output_tools),
        output_schema=output_schema if isinstance(output_schema, dict) else None,
        temperature=temperature if isinstance(temperature, int | float) else None,
        max_tokens=max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else None,
    )
    return request, where


def _with_text(part: ModelRequestPart, text: str) -> ModelRequestPart:
    match part:
        case UserPromptPart() if not isinstance(part.content, str):
            others = [c for c in part.content if not isinstance(c, str | TextContent)]
            return replace(part, content=[text, *others])
        case UserPromptPart() | SystemPromptPart() | ToolReturnPart() | RetryPromptPart():
            return replace(part, content=text)
        case _:  # pragma: no cover - only text-bearing parts become messages
            return part


def apply_request(
    messages: Sequence[ModelMessage],
    params: ModelRequestParameters,
    where: Sequence[Where],
    before: Sequence[hw.Message],
    after: Sequence[hw.Message],
) -> tuple[list[ModelMessage], ModelRequestParameters]:
    """The request with the text ``model.before`` middleware changed, for this request only.

    New message, part and parameter objects are made, so the agent's history and
    its own instructions keep what they had.
    """
    out = list(messages)
    for found, old, new in zip(where, before, after, strict=False):
        if found is None or old.content == new.content:
            continue
        if found == "instructions":
            params = replace(params, instruction_parts=[InstructionPart(content=new.content)])
            continue
        i, j = found
        message = out[i]
        assert isinstance(message, ModelRequest)
        parts = list(message.parts)
        parts[j] = _with_text(parts[j], new.content)
        out[i] = replace(message, parts=parts)
    return out, params


def to_neutral(response: ModelResponse) -> hw.ModelResponse:
    """A Pydantic AI model's answer as the neutral response hooks see."""
    usage = response.usage
    return hw.ModelResponse(
        model=response.model_name,
        text="".join(p.content for p in response.parts if isinstance(p, TextPart)),
        tool_calls=tuple(
            hw.ToolCall(id=p.tool_call_id, name=p.tool_name, arguments=_arguments(p))
            for p in response.parts
            if isinstance(p, ToolCallPart)
        ),
        usage=hw.Usage(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens),
        finish_reason=response.finish_reason,
    )


def from_neutral(response: hw.ModelResponse, params: ModelRequestParameters) -> ModelResponse:
    """A neutral answer (from the harness's model provider) as a Pydantic AI response.

    Structured output goes to the output tool when the agent asks for one, and is
    sent as JSON text otherwise.
    """
    parts: list[TextPart | ToolCallPart] = []
    output, tools = response.output, params.output_tools
    if output is not None and not response.tool_calls and params.output_mode == "tool" and tools:
        key = tools[0].outer_typed_dict_key
        args = (
            {key: output} if key else output if isinstance(output, dict) else {"response": output}
        )
        parts.append(ToolCallPart(tools[0].name, args))
    elif response.text:
        parts.append(TextPart(response.text))
    elif output is not None:
        parts.append(TextPart(json.dumps(output, ensure_ascii=False)))
    parts += [
        ToolCallPart(c.name, dict(c.arguments), tool_call_id=c.id) for c in response.tool_calls
    ]
    usage = RequestUsage(
        input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens
    )
    return ModelResponse(parts=parts, usage=usage, model_name=response.model)


def patch_text(response: ModelResponse, text: str) -> ModelResponse:
    """The model's answer with its text replaced, when output middleware changed it."""
    if "".join(p.content for p in response.parts if isinstance(p, TextPart)) == text:
        return response
    parts: list[Any] = []
    placed = False
    for part in response.parts:
        if isinstance(part, TextPart):
            if not placed:
                parts.append(replace(part, content=text))
                placed = True
            continue
        parts.append(part)
    if not placed:
        parts.insert(0, TextPart(text))
    return replace(response, parts=parts)
