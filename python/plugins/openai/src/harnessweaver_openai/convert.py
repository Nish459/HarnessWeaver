"""Translation between HarnessWeaver's neutral model contracts and the Chat Completions API.

No ``openai`` type leaves this plugin (RULES R7): requests are built as plain
dicts and responses are read attribute by attribute.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import harnessweaver as hw

__all__ = [
    "content_text",
    "from_completion",
    "from_messages",
    "parse_arguments",
    "raise_if_declined",
    "refusal_of",
    "request_kwargs",
    "to_messages",
    "to_tools",
]


def parse_arguments(text: str | None) -> dict[str, Any]:
    """Tool arguments as a dict. Arguments that aren't a JSON object are kept under ``_raw``
    so schema checks reject them rather than the call silently losing them."""
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"_raw": text}
    return value if isinstance(value, dict) else {"_raw": text}


def to_messages(messages: Sequence[hw.Message]) -> list[dict[str, Any]]:
    """Neutral messages as Chat Completions messages."""
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role is hw.Role.TOOL:
            converted.append(
                {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
            )
            continue
        item: dict[str, Any] = {"role": message.role.value, "content": message.content}
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in message.tool_calls
            ]
        if message.name:
            item["name"] = message.name
        converted.append(item)
    return converted


def to_tools(tools: Sequence[hw.ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def request_kwargs(request: hw.ModelRequest, *, max_tokens_param: str) -> dict[str, Any]:
    """The arguments for ``chat.completions.create`` (without ``stream``)."""
    model = request.model or request.alias
    if model is None:
        raise hw.errors.ProviderError(
            "openai.chat needs a model; set models.default or a task model"
        )
    kwargs: dict[str, Any] = {"model": model, "messages": to_messages(request.messages)}
    if request.tools:
        kwargs["tools"] = to_tools(request.tools)
    if request.output_schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "output", "schema": request.output_schema, "strict": False},
        }
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.max_tokens is not None:
        kwargs[max_tokens_param] = request.max_tokens
    return kwargs


def _get(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def refusal_of(message: Any) -> Any:
    """A message's or delta's refusal text. LiteLLM moves it to ``provider_specific_fields``."""
    return _get(message, "refusal") or _get(_get(message, "provider_specific_fields"), "refusal")


def raise_if_declined(response: hw.ModelResponse, refusal: Any) -> None:
    """Stop when the model declined, which reaches us in one of two ways.

    OpenAI sets a ``refusal`` text on the message (see ``refusal_of``). LiteLLM reports
    a Claude refusal as ``finish_reason: content_filter``, also what a provider's content
    filter sets when it cuts an answer short. Either way the answer can't be used.

    Raises:
        ModelRefusal: With ``response``'s usage and cost, and none of its text or the
            refusal's (R9).
    """
    if refusal or response.finish_reason == "content_filter":
        raise hw.errors.ModelRefusal(
            response=response.model_copy(update={"text": "", "tool_calls": ()})
        )


def from_completion(completion: Any, cost: float | None) -> hw.ModelResponse:
    """A ``ChatCompletion`` as a neutral response.

    Raises:
        ModelRefusal: When the model declined (see ``raise_if_declined``).
    """
    choices = _get(completion, "choices") or []
    message = _get(choices[0], "message") if choices else None
    calls = tuple(
        hw.ToolCall(
            id=_get(call, "id"),
            name=_get(_get(call, "function"), "name"),
            arguments=parse_arguments(_get(_get(call, "function"), "arguments")),
        )
        for call in (_get(message, "tool_calls") or [])
        if _get(call, "function") is not None
    )
    usage = _get(completion, "usage")
    response = hw.ModelResponse(
        model=_get(completion, "model"),
        text=(_get(message, "content") or "") if message is not None else "",
        tool_calls=calls,
        usage=hw.Usage(
            input_tokens=_get(usage, "prompt_tokens") or 0,
            output_tokens=_get(usage, "completion_tokens") or 0,
        ),
        cost_usd=cost,
        finish_reason=_get(choices[0], "finish_reason") if choices else None,
    )
    raise_if_declined(response, refusal_of(message))
    return response


def content_text(content: Any) -> str:
    """The text of a message's content: a string, or the text parts of a list."""
    if isinstance(content, str):
        return content
    if isinstance(content, Iterable) and not isinstance(content, Mapping):
        parts = [_get(part, "text") for part in content if _get(part, "type") == "text"]
        return "".join(p for p in parts if isinstance(p, str))
    return ""


def from_messages(messages: Iterable[Any]) -> tuple[hw.Message, ...]:
    """Chat Completions messages (as an app passes them) as neutral messages."""
    converted: list[hw.Message] = []
    for message in messages:
        role = _get(message, "role")
        text = content_text(_get(message, "content"))
        if role in ("system", "developer"):
            converted.append(hw.Message.system(text))
        elif role == "assistant":
            calls = tuple(
                hw.ToolCall(
                    id=_get(call, "id"),
                    name=_get(_get(call, "function"), "name"),
                    arguments=parse_arguments(_get(_get(call, "function"), "arguments")),
                )
                for call in (_get(message, "tool_calls") or [])
            )
            converted.append(hw.Message.assistant(text, calls))
        elif role in ("tool", "function"):
            call_id = _get(message, "tool_call_id") or _get(message, "name") or "unknown"
            converted.append(hw.Message.tool(call_id, text))
        else:
            converted.append(hw.Message.user(text))
    return tuple(converted)
