"""Governed model calls: aliases, budgets, ``model.before`` / ``model.after``, streaming."""

import contextlib
import time
from contextlib import AbstractContextManager
from typing import NoReturn

from opentelemetry.trace import Span
from pydantic import JsonValue

from harnessweaver.core.budgets import resolve_cost
from harnessweaver.core.context.access import MODEL_RETRIES
from harnessweaver.core.context.base import RunContextBase
from harnessweaver.core.errors import (
    HarnessError,
    ProviderError,
    RunBlocked,
    SpecError,
)
from harnessweaver.core.hooks import (
    HookPoint,
    ModelRequestEvent,
    ModelResponseEvent,
    StreamChunkEvent,
)
from harnessweaver.core.messages import ModelRequest, ModelResponse
from harnessweaver.core.outcomes import (
    Block,
    Retry,
)
from harnessweaver.core.ports import (
    ModelProvider,
    StreamingModelProvider,
)
from harnessweaver.core.telemetry import elapsed


class ModelCalls(RunContextBase):
    """One governed model call at a time (DESIGNS No. 16)."""

    def _resolve_model(self, request: ModelRequest) -> ModelRequest:
        access = self.models
        allowed = access.allowed_aliases
        if request.model is not None and request.alias is None:
            if allowed is not None:
                permitted = {access.aliases.get(a, a) for a in allowed}
                if request.model not in permitted:
                    self._model_not_allowed(f"model {request.model!r} isn't allowed")
            return request
        alias = request.alias or (self.task.model if self.task else None) or access.default_alias
        if alias is None:
            return request
        if allowed is not None and alias not in allowed:
            self._model_not_allowed(f"model alias {alias!r} isn't in models.allowed_aliases")
        return request.model_copy(
            update={"alias": alias, "model": access.aliases.get(alias, alias)}
        )

    def _model_not_allowed(self, reason: str) -> NoReturn:
        self.trace.note(
            "harness.models", reason, hook=HookPoint.MODEL_BEFORE, code="model_not_allowed"
        )
        raise RunBlocked(reason, hook=HookPoint.MODEL_BEFORE.value, code="model_not_allowed")

    def _model_span(
        self, request: ModelRequest, provider: str | None
    ) -> AbstractContextManager[Span | None]:
        if self.telemetry is None:
            return contextlib.nullcontext(None)
        return self.telemetry.model_span(request, provider)

    async def generate(
        self, request: ModelRequest, *, provider: ModelProvider | None = None
    ) -> ModelResponse:
        """Make one governed model call: ``model.before``, the provider, ``model.after``.

        Budgets are checked before the call and after it. A ``Retry`` at
        ``model.after`` re-asks the model up to :data:`MODEL_RETRIES` times.
        Adapters pass ``provider`` to send the call through the client they wrap.

        Raises:
            RunInterrupted: When a hook or a budget halts the run.
            ProviderError: When the provider fails.
        """
        request = self._resolve_model(request)
        retries = 0
        while True:
            limit = self.meter.check_model_call(request)
            if limit is not None:
                self._budget_stop(HookPoint.MODEL_BEFORE, limit)
            before = await self.emit(HookPoint.MODEL_BEFORE, ModelRequestEvent(request=request))
            self.halt_on(before)
            sent = before.event.request
            if sent.alias != request.alias:
                sent = self._resolve_model(sent.model_copy(update={"model": None}))
            self.meter.start_model_call()
            name = self.models.provider_name
            with self._model_span(sent, name) as span:
                started = time.perf_counter()
                response = await self._call_provider(sent, provider)
                cost, source = resolve_cost(response, sent, self.models.prices)
                over = self.meter.record_model_call(response.usage, cost)
                usage: dict[str, JsonValue] = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "cost_source": source,
                }
                if cost is not None:
                    usage["cost_usd"] = cost
                self.trace.note(
                    "harness.budget", "model usage", hook=HookPoint.MODEL_AFTER, details=usage
                )
                if span is not None and self.telemetry is not None:
                    self.telemetry.model_done(
                        span,
                        sent,
                        response,
                        name,
                        cost=cost,
                        cost_source=source,
                        seconds=elapsed(started),
                    )
                self._refresh_budget()
                after = await self.emit(
                    HookPoint.MODEL_AFTER, ModelResponseEvent(request=sent, response=response)
                )
                if span is not None and self.telemetry is not None:
                    self.telemetry.model_output(span, after.event.response)
            if over is not None:
                self._budget_stop(HookPoint.MODEL_AFTER, over)
            if isinstance(after.outcome, Retry) and retries < MODEL_RETRIES:
                retries += 1
                self.trace.note(
                    "harness",
                    f"re-asking the model: {after.outcome.reason}",
                    hook=HookPoint.MODEL_AFTER,
                )
                request = sent
                continue
            if isinstance(after.outcome, Retry):
                outcome = Block(
                    reason=f"model retries exhausted: {after.outcome.reason}",
                    code="retry_exhausted",
                )
                raise self.interrupt(HookPoint.MODEL_AFTER, outcome)
            self.halt_on(after)
            return after.event.response

    async def _call_provider(
        self, request: ModelRequest, override: ModelProvider | None
    ) -> ModelResponse:
        provider = override or self.models.provider
        if provider is None:
            raise SpecError("no model provider is configured; set models.provider")
        try:
            if request.stream and isinstance(provider, StreamingModelProvider):
                return await self._stream(provider, request)
            return await provider.generate(request, self._envelope)
        except HarnessError:
            raise
        except Exception as exc:
            raise ProviderError(f"the model provider failed ({type(exc).__name__})") from exc

    async def _stream(
        self, provider: StreamingModelProvider, request: ModelRequest
    ) -> ModelResponse:
        text = ""
        final: ModelResponse | None = None
        stream = provider.stream(request, self._envelope)
        try:
            async for item in stream:
                if isinstance(item, ModelResponse):
                    final = item
                    continue
                event = StreamChunkEvent(request=request, chunk=item, text_so_far=text)
                result = await self.emit(HookPoint.STREAM_CHUNK, event)
                self.halt_on(result)  # a Block cuts the stream here
                chunk = result.event.chunk
                text += chunk.delta
                if self.on_chunk is not None:
                    self.on_chunk(chunk)
        finally:
            closer = getattr(stream, "aclose", None)
            if closer is not None:
                await closer()
        if final is None:
            return ModelResponse(text=text)
        return final.model_copy(update={"text": text})
