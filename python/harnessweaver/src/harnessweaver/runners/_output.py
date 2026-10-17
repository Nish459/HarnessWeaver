"""Shared output handling: typed parsing, ``output.before`` and bounded repair (DESIGNS No. 20)."""

import json
from typing import Any, NoReturn

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError
from pydantic_core import to_jsonable_python

from harnessweaver.core.context import RunContext
from harnessweaver.core.errors import RunBlocked, RunEscalated
from harnessweaver.core.hooks import HookPoint
from harnessweaver.core.messages import Message, ModelResponse
from harnessweaver.core.outcomes import Retry

__all__ = [
    "candidate_of",
    "check_output",
    "give_up",
    "parse_output",
    "repair_message",
    "schema_of",
    "text_of",
    "to_json",
]

_JSON = TypeAdapter[JsonValue](JsonValue)


def to_json(value: Any) -> JsonValue:
    """A JSON-compatible copy of ``value`` (models are dumped in JSON mode)."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return _JSON.validate_python(to_jsonable_python(value))


def text_of(value: Any) -> str:
    """How a value is shown to a model: strings as they are, everything else as JSON."""
    if isinstance(value, str):
        return value
    return json.dumps(to_json(value), ensure_ascii=False)


def candidate_of(response: ModelResponse) -> JsonValue:
    """The model's answer: its structured output if it gave one, else its text."""
    return response.output if response.output is not None else response.text


def schema_of(output_type: type[Any] | None) -> dict[str, JsonValue] | None:
    """The JSON Schema to ask the model for, if the output is a Pydantic model."""
    if isinstance(output_type, type) and issubclass(output_type, BaseModel):
        return _JSON.validate_python(output_type.model_json_schema())  # pyright: ignore[reportReturnType]
    return None


def _problems(exc: ValidationError) -> str:
    # Locations and messages only; Pydantic keeps the offending values in "input" (R9).
    return "; ".join(
        f"{'.'.join(str(p) for p in error['loc']) or 'output'}: {error['msg']}"
        for error in exc.errors()
    )


def parse_output(candidate: JsonValue, output_type: type[Any] | None) -> tuple[Any, str | None]:
    """Turn a candidate into ``output_type``. Returns ``(value, None)`` or ``(None, problem)``."""
    if output_type is None:
        return candidate, None
    if output_type is str:
        return (candidate if isinstance(candidate, str) else text_of(candidate)), None
    data: Any = candidate
    if isinstance(candidate, str):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            return None, "the answer is not valid JSON"
    try:
        if issubclass(output_type, BaseModel):
            return output_type.model_validate(data), None
        return TypeAdapter[Any](output_type).validate_python(data), None
    except ValidationError as exc:
        return None, _problems(exc)


async def check_output(
    ctx: RunContext, value: Any, output_type: type[Any] | None, attempt: int
) -> tuple[Any, str | None]:
    """Fire ``output.before`` on a parsed value.

    Returns ``(value, None)`` when accepted (with any modification applied), or
    ``(None, problem)`` when a middleware asked for a repair.
    """
    schema_name = output_type.__name__ if isinstance(output_type, type) else None
    sent = to_json(value)
    result = await ctx.check_output(sent, attempt=attempt, schema_name=schema_name)
    if isinstance(result.outcome, Retry):
        return None, result.outcome.reason
    if result.event.output != sent:
        return parse_output(result.event.output, output_type)
    return value, None


def repair_message(problem: str) -> Message:
    """The message that asks the model to fix its answer."""
    return Message.user(
        f"Your previous answer was not accepted: {problem}. "
        "Reply again with a corrected answer in the required format."
    )


def give_up(ctx: RunContext, problem: str, repairs: int) -> NoReturn:
    """End the run after the last repair failed, as ``validation.on_failure`` says."""
    on_failure = ctx.task.on_failure if ctx.task is not None else "block"
    reason = f"the output is still invalid after {repairs} repair(s): {problem}"
    ctx.trace.note(
        "harness.validation", reason, hook=HookPoint.OUTPUT_BEFORE, code="validation_failed"
    )
    hook = HookPoint.OUTPUT_BEFORE.value
    if on_failure == "escalate":
        raise RunEscalated(reason, hook=hook, code="validation_failed")
    raise RunBlocked(reason, hook=hook, code="validation_failed")
