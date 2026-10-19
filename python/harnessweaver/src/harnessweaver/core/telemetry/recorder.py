"""``Telemetry``: the spans and metrics one harness records (R9, R13)."""

import contextlib
import time
from collections.abc import Generator, Mapping
from importlib.metadata import version

from opentelemetry import metrics, trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from pydantic import JsonValue

from harnessweaver.core.decisions import Decision, DecisionRequest
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.messages import ModelRequest, ModelResponse, ToolCall
from harnessweaver.core.results import RunResult
from harnessweaver.core.telemetry.names import (
    ERROR_TYPE,
    SCHEMA_URL,
    AttributeValue,
    GenAI,
    HarnessAttr,
    clean_attributes,
    compact_json,
)
from harnessweaver.core.tools import ToolInfo, ToolResult
from harnessweaver.core.trace import TraceEvent, TraceKind

__all__ = ["Telemetry", "elapsed"]


class Telemetry:
    """Spans and metrics for one harness.

    Args:
        capture_content: Record post-redaction content on spans (R9).
        tracer_provider: Use this provider instead of the global one (tests).
        meter_provider: Use this provider instead of the global one (tests).
    """

    def __init__(
        self,
        *,
        capture_content: bool = False,
        tracer_provider: trace.TracerProvider | None = None,
        meter_provider: metrics.MeterProvider | None = None,
    ) -> None:
        release = version("harnessweaver")
        self.capture_content = capture_content
        self._tracer = trace.get_tracer(
            "harnessweaver", release, tracer_provider, schema_url=SCHEMA_URL
        )
        meter = metrics.get_meter("harnessweaver", release, meter_provider, schema_url=SCHEMA_URL)
        self._tokens = meter.create_histogram(
            GenAI.CLIENT_TOKEN_USAGE,
            unit="{token}",
            description="Number of input and output tokens used.",
        )
        self._duration = meter.create_histogram(
            GenAI.CLIENT_OPERATION_DURATION, unit="s", description="GenAI operation duration."
        )
        self._cost = meter.create_counter(
            HarnessAttr.COST_METRIC,
            unit="USD",
            description="Cost of model calls whose cost is known.",
        )

    @contextlib.contextmanager
    def span(
        self,
        name: str,
        attributes: Mapping[str, AttributeValue | None] | None = None,
        *,
        kind: SpanKind = SpanKind.INTERNAL,
    ) -> Generator[Span]:
        """A span that records an error's type, never its message (R9)."""
        with self._tracer.start_as_current_span(
            name,
            kind=kind,
            attributes=clean_attributes(attributes or {}),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield span
            except BaseException as exc:
                span.set_attribute(ERROR_TYPE, type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR))
                raise

    @contextlib.contextmanager
    def run_scope(self, envelope: Envelope) -> Generator[Span]:
        """A current ``harness.run`` span for one run (or one stretch of a resumed run)."""
        span = self._tracer.start_span(
            "harness.run",
            attributes=clean_attributes(
                {
                    HarnessAttr.RUN_ID: envelope.run_id,
                    HarnessAttr.TASK: envelope.task,
                    HarnessAttr.TENANT: envelope.tenant,
                }
            ),
        )
        with trace.use_span(
            span, end_on_exit=True, record_exception=False, set_status_on_exception=False
        ):
            yield span

    @staticmethod
    def trace_id(span: Span) -> str | None:
        """The span's trace id in hex, or ``None`` when no SDK records spans."""
        context = span.get_span_context()
        return trace.format_trace_id(context.trace_id) if context.is_valid else None

    @staticmethod
    def run_done(span: Span, result: RunResult) -> None:
        """Record how a run ended on its span."""
        span.set_attribute(HarnessAttr.RUN_STATUS, result.status.value)
        if result.cost_usd is not None:
            span.set_attribute(HarnessAttr.COST_USD, result.cost_usd)
        span.set_attribute(GenAI.USAGE_INPUT_TOKENS, result.usage.input_tokens)
        span.set_attribute(GenAI.USAGE_OUTPUT_TOKENS, result.usage.output_tokens)
        if result.error is not None:
            span.set_attribute(ERROR_TYPE, result.error.type)
            if result.status.value == "failed":
                span.set_status(Status(StatusCode.ERROR))

    # --- models -----------------------------------------------------------------------------

    def model_span(
        self, request: ModelRequest, provider: str | None
    ) -> contextlib.AbstractContextManager[Span]:
        model = request.model or request.alias
        attributes: dict[str, AttributeValue | None] = {
            GenAI.OPERATION_NAME: "chat",
            GenAI.PROVIDER_NAME: provider,
            GenAI.REQUEST_MODEL: model,
            GenAI.REQUEST_MAX_TOKENS: request.max_tokens,
            GenAI.REQUEST_TEMPERATURE: request.temperature,
            GenAI.REQUEST_STREAM: request.stream or None,
        }
        if self.capture_content:
            messages: list[JsonValue] = [
                m.model_dump(mode="json", exclude_defaults=True, exclude={"extensions"})
                for m in request.messages
            ]
            attributes[GenAI.INPUT_MESSAGES] = compact_json(messages)
        return self.span(f"chat {model or 'unknown'}", attributes, kind=SpanKind.CLIENT)

    def model_done(
        self,
        span: Span,
        request: ModelRequest,
        response: ModelResponse,
        provider: str | None,
        *,
        cost: float | None,
        cost_source: str,
        seconds: float,
    ) -> None:
        """Record a model call's response, usage, cost and duration."""
        usage = response.usage
        attributes = clean_attributes(
            {
                GenAI.RESPONSE_MODEL: response.model,
                GenAI.USAGE_INPUT_TOKENS: usage.input_tokens,
                GenAI.USAGE_OUTPUT_TOKENS: usage.output_tokens,
                GenAI.RESPONSE_FINISH_REASONS: (
                    [response.finish_reason] if response.finish_reason else None
                ),
                HarnessAttr.COST_USD: cost,
                HarnessAttr.COST_SOURCE: cost_source,
            }
        )
        span.set_attributes(attributes)
        metric = clean_attributes(
            {
                GenAI.OPERATION_NAME: "chat",
                GenAI.PROVIDER_NAME: provider,
                GenAI.REQUEST_MODEL: request.model or request.alias,
                GenAI.RESPONSE_MODEL: response.model,
            }
        )
        self._tokens.record(usage.input_tokens, {**metric, GenAI.TOKEN_TYPE: "input"})
        self._tokens.record(usage.output_tokens, {**metric, GenAI.TOKEN_TYPE: "output"})
        self._duration.record(seconds, metric)
        if cost is not None:
            self._cost.add(cost, metric)

    def model_output(self, span: Span, response: ModelResponse) -> None:
        """Record the post-redaction answer, when content capture is on."""
        if self.capture_content:
            message: dict[str, JsonValue] = {"role": "assistant", "content": response.text}
            if response.tool_calls:
                message["tool_calls"] = [c.model_dump(mode="json") for c in response.tool_calls]
            span.set_attribute(GenAI.OUTPUT_MESSAGES, compact_json([message]))

    # --- tools, guards, decisions, approvals ------------------------------------------------

    def tool_span(self, call: ToolCall, tool: ToolInfo) -> contextlib.AbstractContextManager[Span]:
        attributes: dict[str, AttributeValue | None] = {
            GenAI.OPERATION_NAME: "execute_tool",
            GenAI.TOOL_NAME: tool.name,
            GenAI.TOOL_CALL_ID: call.id,
            GenAI.TOOL_TYPE: "function",
        }
        if self.capture_content:
            attributes[GenAI.TOOL_CALL_ARGUMENTS] = compact_json(call.arguments)
        return self.span(f"execute_tool {tool.name}", attributes)

    def tool_done(self, span: Span, result: ToolResult) -> None:
        if result.is_error:
            span.set_attribute(ERROR_TYPE, "tool_error")
            span.set_status(Status(StatusCode.ERROR))
        if self.capture_content:
            span.set_attribute(GenAI.TOOL_CALL_RESULT, compact_json(result.output))

    def guard_span(
        self, name: str, stage: str | None, mode: str
    ) -> contextlib.AbstractContextManager[Span]:
        return self.span(
            "harness.guard",
            {
                HarnessAttr.GUARD_NAME: name,
                HarnessAttr.GUARD_STAGE: stage,
                HarnessAttr.GUARD_MODE: mode,
            },
        )

    @staticmethod
    def guard_done(span: Span, action: str, findings: list[str]) -> None:
        span.set_attribute(HarnessAttr.GUARD_ACTION, action)
        if findings:
            span.set_attribute(HarnessAttr.GUARD_FINDINGS, findings)

    def decision(self, request: DecisionRequest, decision: Decision) -> None:
        with self.span(
            "harness.decision",
            {
                HarnessAttr.DECISION_ROUTER: request.router,
                HarnessAttr.DECISION_KIND: decision.kind.value,
                HarnessAttr.DECISION_CHOICE: decision.choice,
                HarnessAttr.DECISION_CONFIDENCE: decision.confidence,
                HarnessAttr.DECISION_STAGE: decision.stage,
            },
        ):
            pass

    def approval(self, run_id: str, approval_id: str, decision: str) -> None:
        with self.span(
            "harness.approval",
            {
                HarnessAttr.RUN_ID: run_id,
                HarnessAttr.APPROVAL_ID: approval_id,
                HarnessAttr.APPROVAL_DECISION: decision,
            },
        ):
            pass

    @staticmethod
    def trace_event(event: TraceEvent) -> None:
        """Mirror an interesting trace event onto the current span (R13).

        Plain ``Continue`` answers and framework notes stay in the RunTrace only.
        """
        interesting = event.kind is TraceKind.FAILURE or (
            event.kind is TraceKind.OUTCOME
            and event.outcome is not None
            and event.outcome != "continue"
        )
        if not interesting:
            return
        trace.get_current_span().add_event(
            "harness.outcome",
            clean_attributes(
                {
                    HarnessAttr.HOOK: event.hook.value if event.hook else None,
                    HarnessAttr.MIDDLEWARE: event.source,
                    HarnessAttr.BAND: event.band.value if event.band else None,
                    HarnessAttr.OUTCOME: event.outcome.value if event.outcome else None,
                    HarnessAttr.REASON: event.reason,
                    HarnessAttr.CODE: event.code,
                }
            ),
        )


def elapsed(started: float) -> float:
    """Seconds since ``started`` (from :func:`time.perf_counter`), for durations only."""
    return time.perf_counter() - started
