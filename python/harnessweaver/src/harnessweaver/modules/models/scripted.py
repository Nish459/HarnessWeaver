"""The ``scripted`` model provider: answers from a script, with no network (R14).

```yaml
models:
  provider: scripted
  rules:                                    # checked first, against the last message
    - { contains: "refund", reply: { tool_calls: [ { name: refund, arguments: { amount: 5 } } ] } }
    - { role: tool, reply: { text: "Refund done." } }
  replies:                                  # then used in order
    - { output: { vendor: "ACME", total: 12.5 } }
```

Rules match the last message: ``contains`` (case-insensitive), ``matches`` (a
regex) and ``role``. A rule with ``times`` stops matching after that many uses.
When the replies run out the last one repeats, unless ``repeat_last: false``.

Every example's offline overlay uses this provider in place of a real one, so it
ignores settings meant for that provider, such as ``base_url``.
"""

import itertools
import json
import math
import re
from collections.abc import AsyncIterator
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from harnessweaver.core.budgets import estimate_tokens
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import ProviderError
from harnessweaver.core.messages import (
    ModelRequest,
    ModelResponse,
    StreamChunk,
    ToolCall,
    Usage,
)
from harnessweaver.core.plugins import provider

__all__ = ["ScriptedCall", "ScriptedConfig", "ScriptedModel", "ScriptedReply", "ScriptedRule"]


class ScriptedCall(BaseModel):
    """A tool call in a scripted reply; the id is generated when omitted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str | None = None
    name: str = Field(min_length=1)
    arguments: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class ScriptedReply(BaseModel):
    """One scripted answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = ""
    output: JsonValue = Field(default=None, description="Structured output; also sent as text.")
    tool_calls: tuple[ScriptedCall, ...] = ()
    usage: Usage | None = Field(default=None, description="Default: estimated from the text.")
    cost_usd: float | None = Field(default=None, ge=0)
    model: str | None = None
    chunks: tuple[str, ...] | None = Field(default=None, description="How to stream the text.")
    finish_reason: str | None = None
    fail: bool = Field(default=False, description="Raise a ProviderError instead of answering.")


class ScriptedRule(BaseModel):
    """A reply chosen by what the last message says."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contains: str | None = None
    matches: str | None = None
    role: Literal["system", "user", "assistant", "tool"] | None = None
    times: int | None = Field(default=None, gt=0)
    reply: ScriptedReply

    @field_validator("matches")
    @classmethod
    def _compiles(cls, pattern: str | None) -> str | None:
        if pattern is not None:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid pattern: {exc}") from None
        return pattern


class ScriptedConfig(BaseModel):
    """Settings for the ``scripted`` provider. Unknown keys are ignored (see the module doc)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    replies: tuple[ScriptedReply, ...] = ()
    rules: tuple[ScriptedRule, ...] = ()
    repeat_last: bool = True

    @model_validator(mode="after")
    def _has_answers(self) -> Self:
        if not self.replies and not self.rules:
            raise ValueError("a script needs replies or rules")
        return self


@provider(
    port="ModelProvider",
    name="scripted",
    config=ScriptedConfig,
    sample={"replies": [{"text": "ok"}]},
    deterministic=True,
    latency_class="fast",
)
class ScriptedModel:
    """A deterministic model for tests and offline examples.

    ``ScriptedModel.of(reply, ...)`` builds one in code; ``requests`` keeps every
    request it was sent.
    """

    def __init__(self, config: ScriptedConfig) -> None:
        self.config = config
        self.requests: list[ModelRequest] = []
        self._next = 0
        self._used: dict[int, int] = {}
        self._ids = itertools.count(1)

    @classmethod
    def of(
        cls,
        *replies: ScriptedReply | dict[str, Any] | str,
        rules: list[ScriptedRule | dict[str, Any]] | None = None,
        repeat_last: bool = True,
    ) -> Self:
        """Build from replies (a string is a text reply) and optional rules."""
        return cls(
            ScriptedConfig.model_validate(
                {
                    "replies": [{"text": r} if isinstance(r, str) else r for r in replies],
                    "rules": rules or [],
                    "repeat_last": repeat_last,
                }
            )
        )

    def _choose(self, request: ModelRequest) -> ScriptedReply:
        last = request.messages[-1] if request.messages else None
        for index, rule in enumerate(self.config.rules):
            if rule.times is not None and self._used.get(index, 0) >= rule.times:
                continue
            if last is None:
                continue
            if rule.role is not None and last.role.value != rule.role:
                continue
            if rule.contains is not None and rule.contains.lower() not in last.content.lower():
                continue
            if rule.matches is not None and not re.search(rule.matches, last.content):
                continue
            self._used[index] = self._used.get(index, 0) + 1
            return rule.reply
        replies = self.config.replies
        if self._next < len(replies):
            self._next += 1
            return replies[self._next - 1]
        if replies and self.config.repeat_last:
            return replies[-1]
        raise ProviderError("the script has no reply left for this request")

    def _response(self, reply: ScriptedReply, request: ModelRequest) -> ModelResponse:
        if reply.fail:
            raise ProviderError("the script says this call fails")
        text = reply.text
        if not text and reply.output is not None:
            text = json.dumps(reply.output, ensure_ascii=False)
        calls = tuple(
            ToolCall(id=c.id or f"call_{next(self._ids)}", name=c.name, arguments=c.arguments)
            for c in reply.tool_calls
        )
        usage = reply.usage or Usage(
            input_tokens=estimate_tokens(request), output_tokens=math.ceil(len(text) / 4)
        )
        return ModelResponse(
            model=reply.model or request.model or "scripted",
            text=text,
            output=reply.output,
            tool_calls=calls,
            usage=usage,
            cost_usd=reply.cost_usd,
            finish_reason=reply.finish_reason or ("tool_calls" if calls else "stop"),
        )

    async def generate(self, request: ModelRequest, env: Envelope) -> ModelResponse:
        self.requests.append(request)
        return self._response(self._choose(request), request)

    async def stream(
        self, request: ModelRequest, env: Envelope
    ) -> AsyncIterator[StreamChunk | ModelResponse]:
        self.requests.append(request)
        reply = self._choose(request)
        response = self._response(reply, request)
        for index, delta in enumerate(reply.chunks or (response.text,)):
            yield StreamChunk(index=index, delta=delta)
        yield response
