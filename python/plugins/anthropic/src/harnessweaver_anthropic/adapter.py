"""``harness.instrument(Anthropic | AsyncAnthropic)``: govern an app's existing client (L0, L1).

Calls to ``client.messages.create(...)`` go through the harness; everything else
passes through to the real client unchanged. The system prompt and message
text are checked by ``input.before`` and the answer by ``output.before``;
redactions are written back into what the API receives and what the app gets.

Streaming (``stream=True`` or ``client.messages.stream(...)``) through an
instrumented client is *planned*; until then it raises rather than running
ungoverned (R4). ``client.beta.messages`` is not governed.
"""

import copy
from typing import Any

import anyio.to_thread

import harnessweaver as hw
from harnessweaver.adapters import Binding, CallProvider, run_sync
from harnessweaver_anthropic.convert import Origin, from_message, from_params
from harnessweaver_anthropic.messages import provider_error

__all__ = ["AnthropicClientAdapter"]

REACHES = (
    "run.start",
    "input.before",
    "model.before",
    "model.after",
    "output.before",
    "run.error",
    "run.end",
)

_COST_HEADER = "x-litellm-response-cost"


def _with_text(content: Any, text: str) -> Any:
    """``content`` (a string or blocks) with its text replaced by ``text``."""
    if isinstance(content, str) or not isinstance(content, list):
        return text
    blocks: list[Any] = []
    placed = False
    for block in content:
        is_text = (
            block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        ) == "text"
        if not is_text:
            blocks.append(block)
        elif not placed:
            blocks.append({"type": "text", "text": text})
            placed = True
    return blocks if placed else [{"type": "text", "text": text}, *blocks]


def _apply(
    kwargs: dict[str, Any], origin: list[Origin], before: hw.ModelRequest, sent: hw.ModelRequest
) -> dict[str, Any]:
    """The app's arguments with the model and any redacted text from ``sent``."""
    final = dict(kwargs)
    if sent.model:
        final["model"] = sent.model
    messages = [
        copy.deepcopy(m) if isinstance(m, dict) else m for m in kwargs.get("messages") or []
    ]
    for source, neutral_index, block in origin:
        new = sent.messages[neutral_index].content
        if new == before.messages[neutral_index].content:
            continue
        if source is None:
            final["system"] = _with_text(kwargs.get("system"), new)
        elif isinstance(messages[source], dict):
            if block is None:
                messages[source]["content"] = _with_text(messages[source].get("content"), new)
            else:
                result = messages[source]["content"][block]
                result["content"] = _with_text(result.get("content"), new)
    final["messages"] = messages
    return final


def _patched(message: Any, response: hw.ModelResponse) -> Any:
    blocks = list(message.content)
    text = "".join(b.text for b in blocks if b.type == "text")
    if text == response.text:
        return message
    first = next((i for i, b in enumerate(blocks) if b.type == "text"), None)
    if first is None:
        return message
    kept = [
        b.model_copy(update={"text": response.text}) if i == first else b
        for i, b in enumerate(blocks)
        if b.type != "text" or i == first
    ]
    return message.model_copy(update={"content": kept})


class _Messages:
    def __init__(self, inner: Any, binding: Binding, *, sync: bool) -> None:
        self._inner = inner
        self._binding = binding
        self._sync = sync

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def stream(self, **kwargs: Any) -> Any:
        raise hw.errors.SpecError(
            "streaming through harness.instrument() isn't supported yet; use "
            "harness.session(...).generate(stream=True)"
        )

    async def _governed(self, kwargs: dict[str, Any]) -> Any:
        if kwargs.get("stream"):
            self.stream()
        from anthropic import APIError

        request, origin = from_params(kwargs)
        answer: dict[str, Any] = {}

        async def call(sent: hw.ModelRequest) -> hw.ModelResponse:
            final = _apply(kwargs, origin, request, sent)
            create = self._inner.with_raw_response.create
            try:
                if self._sync:
                    raw = await anyio.to_thread.run_sync(lambda: create(**final))
                    message = raw.parse()
                else:
                    raw = await create(**final)
                    message = await raw.parse()
            except APIError as exc:
                raise provider_error(exc) from exc
            answer["message"] = message
            cost = raw.headers.get(_COST_HEADER)
            return from_message(message, float(cost) if cost else None)

        response = await self._binding.generate(request, CallProvider(call))
        return _patched(answer["message"], response)

    def create(self, **kwargs: Any) -> Any:
        if self._sync:
            return run_sync(lambda: self._governed(kwargs))
        return self._governed(kwargs)


class GovernedClient:
    """A stand-in for an Anthropic client whose ``messages.create`` is governed."""

    def __init__(self, client: Any, binding: Binding, *, sync: bool) -> None:
        self._client = client
        self.messages = _Messages(client.messages, binding, sync=sync)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def conformance_sample() -> Any:
    """An offline ``AsyncAnthropic`` client and one call, for the conformance suite (T5)."""
    import httpx2
    from anthropic import AsyncAnthropic

    from harnessweaver.testing import AdapterSample

    body = {
        "id": "msg_conformance",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": "hi"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 3, "output_tokens": 1},
    }
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json=body))
    client = AsyncAnthropic(
        api_key="sk-ant-test-conformance",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=transport),
    )

    async def call(wrapped: Any) -> Any:
        messages = [{"role": "user", "content": "hello"}]
        return await wrapped.messages.create(
            model="claude-opus-5-5", max_tokens=64, messages=messages
        )

    return AdapterSample(client, call)


@hw.adapter(
    "client",
    wraps=["anthropic.Anthropic", "anthropic.AsyncAnthropic"],
    reaches=REACHES,
    sample=conformance_sample,
)
class AnthropicClientAdapter:
    """Governs ``messages.create`` on an ``Anthropic`` or ``AsyncAnthropic`` client."""

    def bind(self, target: Any, binding: Binding) -> Any:
        from anthropic import Anthropic

        return GovernedClient(target, binding, sync=isinstance(target, Anthropic))
