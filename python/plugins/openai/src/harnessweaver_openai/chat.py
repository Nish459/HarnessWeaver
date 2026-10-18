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
(ADR-0012). With ``HARNESSWEAVER_TEST_MODE=1`` the provider refuses to call out (R14).
"""

import os
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

import harnessweaver as hw
from harnessweaver.ports import network_allowed
from harnessweaver_openai.convert import from_completion, parse_arguments, request_kwargs

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
        return from_completion(completion, cost_from_headers(raw.headers, self.config.cost_header))

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
                        yield hw.StreamChunk(index=index, delta=delta.content)
                        index += 1
        except APIError as exc:
            raise provider_error(exc) from exc
        yield hw.ModelResponse(
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
