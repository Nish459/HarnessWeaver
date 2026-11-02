"""The ``openai.chat`` model provider for any OpenAI-compatible endpoint (DESIGNS No. 16).

Point it at LiteLLM Proxy (or OpenAI, vLLM, Ollama):

```yaml
models:
  provider: openai.chat
  base_url: http://litellm:4000      # the gateway owns retries, fallbacks and keys (R5, S1)
  api_key_env: LITELLM_API_KEY
  default: fast
```

SDK retries are off by default because the gateway owns them (R5). The cost
LiteLLM reports in ``x-litellm-response-cost`` is used before any price table
(ADR-0012). A request the model declines ends the run ``blocked`` with code
``model_refusal``. With ``HARNESSWEAVER_TEST_MODE=1`` the provider refuses to call out (R14).
"""

import os
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

import harnessweaver as hw
from harnessweaver.ports import network_allowed
from harnessweaver_openai.convert import (
    from_completion,
    parse_arguments,
    raise_if_declined,
    refusal_of,
    request_kwargs,
)

__all__ = ["OpenAIChat", "OpenAIChatConfig", "cost_from_headers", "provider_error"]


class OpenAIChatConfig(BaseModel):
    """Settings for ``models: {provider: openai.chat, ...}``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str | None = Field(default=None, description="e.g. the LiteLLM Proxy URL.")
    api_key_env: str = Field(
        default="OPENAI_API_KEY", description="Environment variable holding the key (S1)."
    )
    timeout: hw.Duration = Field(default=timedelta(seconds=60))
    max_retries: int = Field(default=0, ge=0, description="0: the gateway retries (R5).")
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    cost_header: str = "x-litellm-response-cost"
    default_headers: dict[str, str] = Field(default_factory=dict[str, str])
    hold_stream: bool = Field(
        default=False,
        description="Deliver a streamed answer's chunks only once it has finished, so nothing "
        "from a declined answer reaches the app, at the cost of live output.",
    )
    block_empty_answers: bool = Field(
        default=False,
        description="Treat an answer with no text and no tool calls as declined. LiteLLM drops a "
        "streamed refusal, leaving only that; but a model may also just have nothing to add.",
    )


def cost_from_headers(headers: Any, name: str) -> float | None:
    """The cost a gateway reported in a response header, if any."""
    value = headers.get(name) if headers is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def provider_error(exc: Exception) -> hw.errors.ProviderError:
    """An ``openai`` exception as a taxonomy error, without its message (R9)."""
    status = getattr(exc, "status_code", None)
    detail = f" (HTTP {status})" if status is not None else ""
    return hw.errors.ProviderError(f"openai.chat: {type(exc).__name__}{detail}")


@hw.provider(
    port="ModelProvider",
    name="openai.chat",
    config=OpenAIChatConfig,
    deterministic=False,
    latency_class="slow",
)
class OpenAIChat:
    """Chat Completions through ``openai.AsyncOpenAI``. The client is created on first use."""

    def __init__(self, config: OpenAIChatConfig, client: Any = None) -> None:
        self.config = config
        self._client = client
        self._injected = client is not None

    def _checked(self, response: hw.ModelResponse) -> hw.ModelResponse:
        """``response``, unless ``block_empty_answers`` says its emptiness means declined."""
        if self.config.block_empty_answers and not (response.text or response.tool_calls):
            raise hw.errors.ModelRefusal(response=response)
        return response

    def _get_client(self) -> Any:
        if self._client is None:
            if not network_allowed():
                raise hw.errors.ProviderError("openai.chat can't call out in test mode (R14)")
            key = os.environ.get(self.config.api_key_env)
            if not key:
                raise hw.errors.ProviderError(f"openai.chat needs ${self.config.api_key_env}")
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=key,
                base_url=self.config.base_url,
                timeout=self.config.timeout.total_seconds(),
                max_retries=self.config.max_retries,
                default_headers=self.config.default_headers or None,
            )
        return self._client

    async def generate(self, request: hw.ModelRequest, env: hw.Envelope) -> hw.ModelResponse:
        from openai import APIError

        kwargs = request_kwargs(request, max_tokens_param=self.config.max_tokens_param)
        try:
            raw = await self._get_client().chat.completions.with_raw_response.create(**kwargs)
            completion = raw.parse()
        except APIError as exc:
            raise provider_error(exc) from exc
        return self._checked(
            from_completion(completion, cost_from_headers(raw.headers, self.config.cost_header))
        )

    async def stream(
        self, request: hw.ModelRequest, env: hw.Envelope
    ) -> AsyncIterator[hw.StreamChunk | hw.ModelResponse]:
        from openai import APIError

        kwargs = request_kwargs(request, max_tokens_param=self.config.max_tokens_param)
        kwargs.update(stream=True, stream_options={"include_usage": True})
        text = ""
        calls: dict[int, dict[str, str]] = {}
        usage = hw.Usage()
        model: str | None = None
        finish: str | None = None
        refusal: Any = None
        held: list[hw.StreamChunk] = []
        try:
            raw = await self._get_client().chat.completions.with_raw_response.create(**kwargs)
            cost = cost_from_headers(raw.headers, self.config.cost_header)
            index = 0
            async for chunk in raw.parse():
                model = chunk.model or model
                if chunk.usage is not None:
                    usage = hw.Usage(
                        input_tokens=chunk.usage.prompt_tokens,
                        output_tokens=chunk.usage.completion_tokens,
                    )
                for choice in chunk.choices:
                    finish = choice.finish_reason or finish
                    delta = choice.delta
                    refusal = refusal_of(delta) or refusal
                    for call in delta.tool_calls or []:
                        entry = calls.setdefault(
                            call.index, {"id": "", "name": "", "arguments": ""}
                        )
                        entry["id"] = call.id or entry["id"]
                        if call.function is not None:
                            entry["name"] += call.function.name or ""
                            entry["arguments"] += call.function.arguments or ""
                    if delta.content:
                        text += delta.content
                        piece = hw.StreamChunk(index=index, delta=delta.content)
                        index += 1
                        if self.config.hold_stream:
                            held.append(piece)
                        else:
                            yield piece
        except APIError as exc:
            raise provider_error(exc) from exc
        response = hw.ModelResponse(
            model=model,
            text=text,
            tool_calls=tuple(
                hw.ToolCall(
                    id=c["id"] or f"call_{i}",
                    name=c["name"],
                    arguments=parse_arguments(c["arguments"]),
                )
                for i, c in sorted(calls.items())
            ),
            usage=usage,
            cost_usd=cost,
            finish_reason=finish,
        )
        # Only now: the usage comes last, and the signal can follow text already streamed.
        raise_if_declined(response, refusal)
        self._checked(response)
        for piece in held:
            yield piece
        yield response
