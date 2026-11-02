"""Translation between HarnessWeaver's neutral model contracts and the Claude Messages API.

No ``anthropic`` type leaves this plugin (RULES R7). Each answer's own content
blocks (including thinking blocks) are kept in ``extensions["anthropic"]`` and
replayed unchanged on the next request, as the API requires for reasoning to
carry over between turns. When the harness changed an answer (a redaction, say),
that turn is rebuilt from the neutral message instead, without its thinking; the
same choice is made on every later request, so the history stays append-only.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, cast

from pydantic import JsonValue

import harnessweaver as hw

__all__ = [
    "EXTENSION",
    "Origin",
    "assistant_content",
    "from_message",
    "from_params",
    "request_kwargs",
    "text_of_blocks",
]

EXTENSION: Final = "anthropic"


def _get(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _dump(block: Any) -> dict[str, Any]:
    if isinstance(block, Mapping):
        return dict(block)
    return block.model_dump(mode="json", exclude_none=True)


def _echo_blocks(content: Sequence[Any]) -> list[dict[str, Any]]:
    """The blocks to replay: after a mid-answer fallback, blocks of the declined model
    before the last ``fallback`` marker are left out, as the API asks."""
    blocks = [_dump(b) for b in content]
    last = max((i for i, b in enumerate(blocks) if b.get("type") == "fallback"), default=-1)
    dropped = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}
    return [
        b
        for i, b in enumerate(blocks)
        if b.get("type") != "fallback" and not (i < last and b.get("type") in dropped)
    ]


def _extension(
    content: list[dict[str, Any]], text: str, calls: tuple[hw.ToolCall, ...]
) -> JsonValue:
    """What an answer replays with: its blocks, plus what they said, to detect edits."""
    stored: dict[str, JsonValue] = {
        "content": [cast("JsonValue", block) for block in content],
        "text": text,
        "tool_calls": [c.model_dump(mode="json") for c in calls],
    }
    return stored


def text_of_blocks(content: Iterable[Any]) -> str:
    return "".join(_get(b, "text") or "" for b in content if _get(b, "type") == "text")


def from_message(message: Any, cost: float | None) -> hw.ModelResponse:
    """A Messages API answer as a neutral response.

    Raises:
        ModelRefusal: When the model declined (``stop_reason: refusal``); nothing
            else in the answer is usable, only what it used.
    """
    content = _get(message, "content") or []
    calls = tuple(
        hw.ToolCall(id=_get(b, "id"), name=_get(b, "name"), arguments=dict(_get(b, "input") or {}))
        for b in content
        if _get(b, "type") == "tool_use"
    )
    usage = _get(message, "usage")
    input_tokens = sum(
        _get(usage, field) or 0
        for field in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )
    spent = hw.Usage(input_tokens=input_tokens, output_tokens=_get(usage, "output_tokens") or 0)
    if _get(message, "stop_reason") == "refusal":
        details = _get(message, "stop_details")
        category = _get(details, "category") if details is not None else None
        raise hw.errors.ModelRefusal(
            response=hw.ModelResponse(
                model=_get(message, "model"),
                usage=spent,
                cost_usd=cost,
                finish_reason="refusal",
            ),
            category=category if isinstance(category, str) else None,
        )
    text = text_of_blocks(content)
    return hw.ModelResponse(
        model=_get(message, "model"),
        text=text,
        tool_calls=calls,
        usage=spent,
        cost_usd=cost,
        finish_reason=_get(message, "stop_reason"),
        extensions={EXTENSION: _extension(_echo_blocks(content), text, calls)},
    )


def assistant_content(message: hw.Message) -> list[dict[str, Any]]:
    """An assistant turn's content: its own blocks when unchanged, else rebuilt."""
    stored = message.extensions.get(EXTENSION)
    if isinstance(stored, dict):
        calls = [c.model_dump(mode="json") for c in message.tool_calls]
        if stored.get("text") == message.content and stored.get("tool_calls") == calls:
            content = stored.get("content")
            if isinstance(content, list):
                return [dict(b) for b in content if isinstance(b, dict)]
    blocks: list[dict[str, Any]] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    blocks.extend(
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
        for c in message.tool_calls
    )
    return blocks


def _messages(messages: Sequence[hw.Message]) -> tuple[list[str], list[dict[str, Any]]]:
    system: list[str] = []
    converted: list[dict[str, Any]] = []
    leading = True
    for message in messages:
        if message.role is hw.Role.SYSTEM:
            if leading:
                system.append(message.content)
            else:
                converted.append({"role": "system", "content": message.content})
            continue
        leading = False
        if message.role is hw.Role.TOOL:
            result = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.content,
            }
            last = converted[-1] if converted else None
            # Parallel tool results go back in one user message.
            joinable = (
                last is not None
                and last["role"] == "user"
                and isinstance(last["content"], list)
                and all(b.get("type") == "tool_result" for b in last["content"])
            )
            if last is not None and joinable:
                last["content"].append(result)
                continue
            converted.append({"role": "user", "content": [result]})
        elif message.role is hw.Role.ASSISTANT:
            converted.append({"role": "assistant", "content": assistant_content(message)})
        else:
            converted.append({"role": "user", "content": message.content})
    return system, converted


def request_kwargs(
    request: hw.ModelRequest,
    *,
    model: str,
    max_tokens: int,
    thinking: str,
    effort: str | None,
    structured_outputs: bool,
    sampling: bool,
) -> dict[str, Any]:
    """The arguments for ``messages.create`` (without ``stream``)."""
    system, messages = _messages(request.messages)
    kwargs: dict[str, Any] = {
        "model": request.model or request.alias or model,
        "max_tokens": request.max_tokens or max_tokens,
        "messages": messages,
    }
    output_config: dict[str, Any] = {}
    if request.output_schema is not None:
        if structured_outputs:
            output_config["format"] = {"type": "json_schema", "schema": request.output_schema}
        else:
            system.append(
                "Reply with only a JSON value that matches this JSON Schema:\n"
                + json.dumps(request.output_schema, sort_keys=True)
            )
    if effort is not None:
        output_config["effort"] = effort
    if output_config:
        kwargs["output_config"] = output_config
    if system:
        kwargs["system"] = "\n\n".join(system)
    if request.tools:
        kwargs["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in request.tools
        ]
    if thinking == "adaptive":
        kwargs["thinking"] = {"type": "adaptive"}
    if sampling and request.temperature is not None:
        # The SDK no longer types sampling parameters; older models still take them.
        kwargs["extra_body"] = {"temperature": request.temperature}
    return kwargs


# --- what an app passes to messages.create -------------------------------------------------------


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return text_of_blocks(content or [])


type Origin = tuple[int | None, int, int | None]
"""``(message index or None for the system prompt, neutral index, tool_result block index)``."""


def from_params(kwargs: Mapping[str, Any]) -> tuple[hw.ModelRequest, list[Origin]]:
    """An app's ``messages.create`` arguments as a neutral request.

    Also returns where each neutral message came from, so redactions can be
    written back into the app's own arguments.
    """
    neutral: list[hw.Message] = []
    origin: list[Origin] = []
    system = kwargs.get("system")
    if system:
        neutral.append(hw.Message.system(_content_text(system)))
        origin.append((None, len(neutral) - 1, None))
    for index, message in enumerate(kwargs.get("messages") or []):
        role = _get(message, "role")
        content = _get(message, "content")
        if role == "assistant":
            blocks = content if isinstance(content, list) else []
            calls = tuple(
                hw.ToolCall(
                    id=_get(b, "id"), name=_get(b, "name"), arguments=dict(_get(b, "input") or {})
                )
                for b in blocks
                if _get(b, "type") == "tool_use"
            )
            neutral.append(hw.Message.assistant(_content_text(content), calls))
            origin.append((index, len(neutral) - 1, None))
            continue
        if role == "system":
            neutral.append(hw.Message.system(_content_text(content)))
            origin.append((index, len(neutral) - 1, None))
            continue
        blocks = content if isinstance(content, list) else []
        for position, block in enumerate(blocks):
            if _get(block, "type") == "tool_result":
                call_id = _get(block, "tool_use_id") or "unknown"
                neutral.append(hw.Message.tool(call_id, _content_text(_get(block, "content"))))
                origin.append((index, len(neutral) - 1, position))
        text = _content_text(content)
        if text or not blocks:
            neutral.append(hw.Message.user(text))
            origin.append((index, len(neutral) - 1, None))
    max_tokens = kwargs.get("max_tokens")
    return (
        hw.ModelRequest(
            model=kwargs.get("model"),
            messages=tuple(neutral),
            max_tokens=max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else None,
        ),
        origin,
    )
