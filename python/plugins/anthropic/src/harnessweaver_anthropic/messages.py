"""The ``anthropic.messages`` model provider: Claude through the Messages API (DESIGNS No. 16).

```yaml
models:
  provider: anthropic.messages
  default: strong
  aliases: { strong: claude-opus-5-5, fast: claude-haiku-5-5 }
  effort: high                    # output_config.effort; unset uses the model's default
```

* Thinking is adaptive (``thinking: {type: adaptive}``); set ``thinking: none`` to omit it.
* Server-side refusal fallbacks are on by default (``fallbacks: default``, beta
  ``server-side-fallback-2026-07-01``): a request a model declines for policy
  reasons is re-run server-side on Anthropic's recommended fallback model. On a
  model without fallbacks the request simply runs alone. Set ``fallbacks: none``
  behind a gateway that rejects beta parameters.
* A request that is still declined ends the run ``blocked`` with code ``model_refusal``.
* ``temperature`` is not sent unless ``sampling: true``: current Claude models
  reject sampling parameters.
* Credentials: the SDK's own resolution (``ANTHROPIC_API_KEY``, ``ANTHROPIC_AUTH_TOKEN``,
  ``ant auth login`` profiles, workload identity), or ``api_key_env`` to name a variable.
  When none can be found, the call fails with a ``ProviderError`` that says what to set.
* With ``HARNESSWEAVER_TEST_MODE=1`` the provider refuses to call out (R14).
"""

import os
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

import harnessweaver as hw
from harnessweaver.ports import network_allowed
from harnessweaver_anthropic.convert import from_message, request_kwargs

__all__ = ["FALLBACK_BETA", "AnthropicMessages", "AnthropicMessagesConfig", "provider_error"]

FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"
DEFAULT_MODEL: Final = "claude-opus-5-5"
NO_CREDENTIALS: Final = (
    "anthropic.messages found no credentials: set ANTHROPIC_API_KEY, log in with "
    "`ant auth login`, or name the key's variable in models.api_key_env"
)


class AnthropicMessagesConfig(BaseModel):
    """Settings for ``models: {provider: anthropic.messages, ...}``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(default=DEFAULT_MODEL, description="When a request names no model.")
    max_tokens: int = Field(default=16_000, gt=0, description="When a request sets none.")
    stream_max_tokens: int = Field(default=64_000, gt=0)
    thinking: Literal["adaptive", "none"] = "adaptive"
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    fallbacks: Literal["default", "none"] = "default"
    structured_outputs: bool = Field(
        default=False,
        description="Send output schemas as output_config.format; they must meet the API's "
        "structured-output rules. Otherwise the schema goes in the system prompt.",
    )
    sampling: bool = Field(default=False, description="Forward temperature (older models only).")
    base_url: str | None = None
    api_key_env: str | None = Field(default=None, description="Read the key from this variable.")
    timeout: hw.Duration = Field(default=timedelta(minutes=10))
    max_retries: int = Field(default=2, ge=0, description="Set 0 behind a gateway (R5).")
    cost_header: str = "x-litellm-response-cost"
    hold_stream: bool = Field(
        default=False,
        description="Deliver a streamed answer's chunks only once it has finished, so nothing "
        "from a declined answer reaches the app, at the cost of live output.",
    )


def provider_error(exc: Exception) -> hw.errors.ProviderError:
    """An ``anthropic`` exception as a taxonomy error, without its message (R9)."""
    status = getattr(exc, "status_code", None)
    detail = f" (HTTP {status})" if status is not None else ""
    return hw.errors.ProviderError(f"anthropic.messages: {type(exc).__name__}{detail}")


def _credentials_error(exc: Exception, client: Any) -> hw.errors.ProviderError | None:
    """A clear error for ``exc`` when the SDK couldn't find credentials, else ``None``.

    The SDK raises ``CredentialsError`` when a profile or identity token it was
    pointed at can't be loaded. Its message names the file or variable and never
    holds a secret or any content (R9), so it is kept. It raises a bare ``TypeError``
    when it builds a request with nothing to authenticate it: no key, no token and
    no credentials provider. A ``TypeError`` from a client that has one of those is
    some other fault, and is left alone.
    """
    from anthropic import CredentialsError

    if isinstance(exc, CredentialsError):
        return hw.errors.ProviderError(f"anthropic.messages: {exc}")
    found = (getattr(client, name, None) for name in ("api_key", "auth_token", "credentials"))
    if client is None or any(value is not None for value in found):
        return None
    return hw.errors.ProviderError(NO_CREDENTIALS)


def _cost(headers: Any, name: str) -> float | None:
    value = headers.get(name) if headers is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


@hw.provider(
    port="ModelProvider",
    name="anthropic.messages",
    config=AnthropicMessagesConfig,
    deterministic=False,
    latency_class="slow",
)
class AnthropicMessages:
    """Claude through ``anthropic.AsyncAnthropic``. The client is created on first use."""

    def __init__(self, config: AnthropicMessagesConfig, client: Any = None) -> None:
        self.config = config
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            if not network_allowed():
                raise hw.errors.ProviderError(
                    "anthropic.messages can't call out in test mode (R14)"
                )
            from anthropic import AsyncAnthropic

            options: dict[str, Any] = {
                "timeout": self.config.timeout.total_seconds(),
                "max_retries": self.config.max_retries,
            }
            if self.config.base_url is not None:
                options["base_url"] = self.config.base_url
            if self.config.api_key_env is not None:
                key = os.environ.get(self.config.api_key_env)
                if not key:
                    raise hw.errors.ProviderError(
                        f"anthropic.messages needs ${self.config.api_key_env}"
                    )
                options["api_key"] = key
            self._client = AsyncAnthropic(**options)
        return self._client

    def _kwargs(self, request: hw.ModelRequest, *, stream: bool) -> dict[str, Any]:
        config = self.config
        kwargs = request_kwargs(
            request,
            model=config.model,
            max_tokens=config.stream_max_tokens if stream else config.max_tokens,
            thinking=config.thinking,
            effort=config.effort,
            structured_outputs=config.structured_outputs,
            sampling=config.sampling,
        )
        if config.fallbacks == "default":
            kwargs["fallbacks"] = "default"
            kwargs["betas"] = [FALLBACK_BETA]
        return kwargs

    def _endpoint(self, kwargs: dict[str, Any]) -> Any:
        client = self._get_client()
        return client.beta.messages if "betas" in kwargs else client.messages

    async def generate(self, request: hw.ModelRequest, env: hw.Envelope) -> hw.ModelResponse:
        from anthropic import APIError, CredentialsError

        kwargs = self._kwargs(request, stream=False)
        try:
            raw = await self._endpoint(kwargs).with_raw_response.create(**kwargs)
            message = await raw.parse()
        except APIError as exc:
            raise provider_error(exc) from exc
        except (CredentialsError, TypeError) as exc:
            if (clear := _credentials_error(exc, self._client)) is None:
                raise
            raise clear from exc
        return from_message(message, _cost(raw.headers, self.config.cost_header))

    async def stream(
        self, request: hw.ModelRequest, env: hw.Envelope
    ) -> AsyncIterator[hw.StreamChunk | hw.ModelResponse]:
        from anthropic import APIError, CredentialsError

        kwargs = self._kwargs(request, stream=True)
        index = 0
        held: list[hw.StreamChunk] = []
        try:
            async with self._endpoint(kwargs).stream(**kwargs) as stream:
                async for event in stream:
                    delta: Any = getattr(event, "delta", None)
                    if (
                        event.type == "content_block_delta"
                        and getattr(delta, "type", None) == "text_delta"
                    ):
                        piece = hw.StreamChunk(index=index, delta=delta.text)
                        index += 1
                        if self.config.hold_stream:
                            held.append(piece)
                        else:
                            yield piece
                message = await stream.get_final_message()
        except APIError as exc:
            raise provider_error(exc) from exc
        except (CredentialsError, TypeError) as exc:
            if (clear := _credentials_error(exc, self._client)) is None:
                raise
            raise clear from exc
        response = from_message(message, None)  # raises if the model declined
        for piece in held:
            yield piece
        yield response
