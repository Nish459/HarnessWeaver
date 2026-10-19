"""Span, attribute and metric names, pinned to the GenAI semantic conventions."""

import json
from collections.abc import Mapping
from typing import Final

from pydantic import JsonValue

__all__ = [
    "ERROR_TYPE",
    "SCHEMA_URL",
    "SEMCONV_VERSION",
    "AttributeValue",
    "GenAI",
    "HarnessAttr",
    "clean_attributes",
    "compact_json",
]

SEMCONV_VERSION: Final = "1.42.0"
"""The semantic conventions the GenAI names below come from. In 1.42.0 they moved
to the ``semantic-conventions-genai`` repository, still in Development."""

SCHEMA_URL: Final = f"https://opentelemetry.io/schemas/{SEMCONV_VERSION}"

ERROR_TYPE: Final = "error.type"

type AttributeValue = str | bool | int | float | list[str]


class GenAI:
    """GenAI semantic-convention names used by HarnessWeaver."""

    OPERATION_NAME: Final = "gen_ai.operation.name"
    PROVIDER_NAME: Final = "gen_ai.provider.name"
    REQUEST_MODEL: Final = "gen_ai.request.model"
    REQUEST_MAX_TOKENS: Final = "gen_ai.request.max_tokens"
    REQUEST_TEMPERATURE: Final = "gen_ai.request.temperature"
    REQUEST_STREAM: Final = "gen_ai.request.stream"
    RESPONSE_MODEL: Final = "gen_ai.response.model"
    RESPONSE_FINISH_REASONS: Final = "gen_ai.response.finish_reasons"
    USAGE_INPUT_TOKENS: Final = "gen_ai.usage.input_tokens"
    USAGE_OUTPUT_TOKENS: Final = "gen_ai.usage.output_tokens"
    TOKEN_TYPE: Final = "gen_ai.token.type"
    TOOL_NAME: Final = "gen_ai.tool.name"
    TOOL_CALL_ID: Final = "gen_ai.tool.call.id"
    TOOL_TYPE: Final = "gen_ai.tool.type"
    TOOL_CALL_ARGUMENTS: Final = "gen_ai.tool.call.arguments"
    TOOL_CALL_RESULT: Final = "gen_ai.tool.call.result"
    INPUT_MESSAGES: Final = "gen_ai.input.messages"
    OUTPUT_MESSAGES: Final = "gen_ai.output.messages"
    CLIENT_TOKEN_USAGE: Final = "gen_ai.client.token.usage"
    CLIENT_OPERATION_DURATION: Final = "gen_ai.client.operation.duration"


class HarnessAttr:
    """The framework's own ``harness.*`` attribute names."""

    RUN_ID: Final = "harness.run.id"
    RUN_STATUS: Final = "harness.run.status"
    TASK: Final = "harness.task"
    TENANT: Final = "harness.tenant"
    HOOK: Final = "harness.hook"
    OUTCOME: Final = "harness.outcome"
    BAND: Final = "harness.band"
    MIDDLEWARE: Final = "harness.middleware"
    REASON: Final = "harness.reason"
    CODE: Final = "harness.code"
    COST_USD: Final = "harness.cost.usd"
    COST_SOURCE: Final = "harness.cost.source"
    DECISION_ROUTER: Final = "harness.decision.router"
    DECISION_KIND: Final = "harness.decision.kind"
    DECISION_CHOICE: Final = "harness.decision.choice"
    DECISION_CONFIDENCE: Final = "harness.decision.confidence"
    DECISION_STAGE: Final = "harness.decision.stage"
    GUARD_NAME: Final = "harness.guard.name"
    GUARD_STAGE: Final = "harness.guard.stage"
    GUARD_ACTION: Final = "harness.guard.action"
    GUARD_MODE: Final = "harness.guard.mode"
    GUARD_FINDINGS: Final = "harness.guard.findings"
    APPROVAL_ID: Final = "harness.approval.id"
    APPROVAL_DECISION: Final = "harness.approval.decision"
    COST_METRIC: Final = "harness.cost"


def clean_attributes(attributes: Mapping[str, AttributeValue | None]) -> dict[str, AttributeValue]:
    return {key: value for key, value in attributes.items() if value is not None}


def compact_json(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
