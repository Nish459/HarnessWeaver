"""``harness.instrument(OpenAI | AsyncOpenAI)``: govern an app's existing client (L0, L1).

Calls to ``client.chat.completions.create(...)`` go through the harness; every
other attribute passes through to the real client unchanged. Message text is
checked by ``input.before`` and the answer by ``output.before``; redactions are
written back into the messages the API receives and the answer the app gets.

Streaming (``stream=True``) through an instrumented client is *planned*; until
then it raises, rather than running ungoverned (R4).
"""

import copy
from collections.abc import Callable
from typing import Any

import anyio.to_thread

import harnessweaver as hw
from harnessweaver.adapters import Binding, CallProvider, run_sync
from harnessweaver_openai.chat import cost_from_headers, provider_error
from harnessweaver_openai.convert import content_text, from_completion, from_messages

__all__ = ["OpenAIClientAdapter"]

REACHES = (
    "run.start",
    "input.before",
    "model.before",
    "model.after",
    "output.before",
    "run.error",
    "run.end",
)


def _neutral(kwargs: dict[str, Any]) -> hw.ModelRequest:
    max_tokens = kwargs.get("max_completion_tokens") or kwargs.get("max_tokens")
    temperature = kwargs.get("temperature")
    return hw.ModelRequest(
        model=kwargs.get("model"),
        messages=from_messages(kwargs.get("messages") or []),
        temperature=temperature if isinstance(temperature, int | float) else None,
        max_tokens=max_tokens if isinstance(max_tokens, int) else None,
    )


def _apply(kwargs: dict[str, Any], sent: hw.ModelRequest) -> dict[str, Any]:
    """The app's arguments with the model and any redacted message text from ``sent``."""
    final = dict(kwargs)
    if sent.model:
        final["model"] = sent.model
    messages = [copy.copy(m) if isinstance(m, dict) else m for m in kwargs.get("messages") or []]
    for index, (message, neutral) in enumerate(zip(messages, sent.messages, strict=False)):
        if not isinstance(message, dict):
            continue
        original = content_text(message.get("content"))
        if neutral.content == original:
            continue
        content = message.get("content")
        if isinstance(content, list):
            others = [p for p in content if not (isinstance(p, dict) and p.get("type") == "text")]
            message["content"] = [{"type": "text", "text": neutral.content}, *others]
        else:
            message["content"] = neutral.content
        messages[index] = message
    final["messages"] = messages
    return final


def _patched(completion: Any, response: hw.ModelResponse) -> Any:
    """The SDK's answer, with the text replaced if output middleware changed it."""
    choices = getattr(completion, "choices", None)
    if not choices or (choices[0].message.content or "") == response.text:
        return completion
    message = choices[0].message.model_copy(update={"content": response.text})
    first = choices[0].model_copy(update={"message": message})
    return completion.model_copy(update={"choices": [first, *choices[1:]]})


class _Completions:
    def __init__(self, inner: Any, binding: Binding, *, sync: bool) -> None:
        self._inner = inner
        self._binding = binding
        self._sync = sync

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def _governed(self, kwargs: dict[str, Any]) -> Any:
        if kwargs.get("stream"):
            raise hw.errors.SpecError(
                "streaming through harness.instrument() isn't supported yet; use "
                "harness.session(...).generate(stream=True)"
            )
        from openai import APIError

        answer: dict[str, Any] = {}

        async def call(sent: hw.ModelRequest) -> hw.ModelResponse:
            final = _apply(kwargs, sent)
            create: Callable[..., Any] = self._inner.with_raw_response.create
            try:
                if self._sync:
                    raw = await anyio.to_thread.run_sync(lambda: create(**final))
                else:
                    raw = await create(**final)
                completion = raw.parse()
            except APIError as exc:
                raise provider_error(exc) from exc
            answer["completion"] = completion
            return from_completion(
                completion, cost_from_headers(raw.headers, "x-litellm-response-cost")
            )

        response = await self._binding.generate(_neutral(kwargs), CallProvider(call))
        return _patched(answer["completion"], response)

    def create(self, **kwargs: Any) -> Any:
        if self._sync:
            return run_sync(lambda: self._governed(kwargs))
        return self._governed(kwargs)


class _Chat:
    def __init__(self, inner: Any, binding: Binding, *, sync: bool) -> None:
        self._inner = inner
        self.completions = _Completions(inner.completions, binding, sync=sync)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class GovernedClient:
    """A stand-in for an OpenAI client whose chat completions are governed."""

    def __init__(self, client: Any, binding: Binding, *, sync: bool) -> None:
        self._client = client
        self.chat = _Chat(client.chat, binding, sync=sync)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


@hw.adapter("client", wraps=["openai.OpenAI", "openai.AsyncOpenAI"], reaches=REACHES)
class OpenAIClientAdapter:
    """Governs ``chat.completions.create`` on an ``OpenAI`` or ``AsyncOpenAI`` client."""

    def bind(self, target: Any, binding: Binding) -> Any:
        from openai import OpenAI

        return GovernedClient(target, binding, sync=isinstance(target, OpenAI))
