"""The ``direct`` runner: one typed generate, with an optional bounded tool loop (ADR-0011).

There is no planning, memory or templating here (R12). The loop is:

1. Send the task's prompt and the input to the model, offering the task's tools.
2. If the model asks for tools, run each one governed (``tool.before`` / ``tool.after``)
   and send the results back. At most ``max_steps`` model calls do this.
3. When the model answers, parse it into the task's output type and fire
   ``output.before``. A rejected answer is repaired up to ``max_repairs`` times.

The runner is resumable: before each step that can suspend it records where
it is, and after an approval it continues from exactly that point.
"""

import json
from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from harnessweaver.core.context import RunContext
from harnessweaver.core.errors import RunBlocked, SpecError
from harnessweaver.core.hooks import HookPoint
from harnessweaver.core.messages import Message, ModelRequest, ToolCall
from harnessweaver.core.plugins import runner
from harnessweaver.core.tools import ToolResult
from harnessweaver.runners._output import (
    candidate_of,
    check_output,
    give_up,
    parse_output,
    repair_message,
    schema_of,
    text_of,
    to_json,
)

__all__ = ["ALL_HOOKS", "DirectConfig", "DirectRunner"]

ALL_HOOKS = tuple(HookPoint)


class DirectConfig(BaseModel):
    """Settings for ``runner: {use: direct, ...}``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_steps: int = Field(
        default=8, ge=1, le=100, description="Model calls in the tool loop, not counting repairs."
    )


def _variables(value: Any) -> dict[str, Any]:
    data = to_json(value)
    if isinstance(data, dict):
        return {**data, "input": data}
    return {"input": data}


def _tool_content(result: ToolResult) -> str:
    if isinstance(result.output, str):
        return result.output
    return json.dumps(result.output, ensure_ascii=False)


@runner("direct", reaches=ALL_HOOKS, config=DirectConfig, resumable=True)
class DirectRunner:
    """Run a task as one governed generate with a bounded tool loop."""

    def __init__(self, config: DirectConfig | None = None) -> None:
        self.config = config or DirectConfig()

    async def _start(self, ctx: RunContext, input: Any) -> dict[str, JsonValue]:
        task = ctx.task
        assert task is not None
        messages: list[Message] = []
        if task.prompt is not None:
            if ctx.prompts is None:
                raise SpecError(f"task {task.name} names a prompt, but no prompts are configured")
            messages.append(
                Message.system(await ctx.prompts.render(task.prompt, _variables(input)))
            )
        messages.append(Message.user(text_of(input)))
        return {
            "phase": "model",
            "messages": [m.model_dump(mode="json") for m in messages],
            "step": 0,
            "attempt": 0,
        }

    async def execute(
        self, ctx: RunContext, input: Any, resume: Mapping[str, JsonValue] | None
    ) -> Any:
        task = ctx.task
        if task is None:
            raise SpecError("the direct runner needs a task")
        state: dict[str, Any] = dict(resume) if resume else await self._start(ctx, input)
        messages = [Message.model_validate(m) for m in state["messages"]]
        tools = tuple(d.spec for d in ctx.tool_specs(task.tools))
        schema = schema_of(task.output_type)

        def save() -> None:
            state["messages"] = [m.model_dump(mode="json") for m in messages]
            ctx.set_resume_point(cast("dict[str, JsonValue]", state))

        while True:
            if state["phase"] == "model":
                if state["step"] >= self.config.max_steps:
                    reason = f"the tool loop reached max_steps ({self.config.max_steps})"
                    ctx.trace.note("direct", reason, code="max_steps")
                    raise RunBlocked(reason, code="max_steps")
                request = ModelRequest(messages=tuple(messages), tools=tools, output_schema=schema)
                response = await ctx.generate(request)
                if state.get("repairing"):
                    state["repairing"] = False
                else:
                    state["step"] += 1
                if response.tool_calls:
                    messages.append(
                        Message.assistant(response.text, response.tool_calls, response.extensions)
                    )
                    state["phase"] = "tools"
                    state["calls"] = [c.model_dump(mode="json") for c in response.tool_calls]
                    state["index"] = 0
                else:
                    candidate = candidate_of(response)
                    messages.append(
                        Message.assistant(text_of(candidate), extensions=response.extensions)
                    )
                    state["phase"] = "output"
                    state["candidate"] = candidate
            elif state["phase"] == "tools":
                calls = [ToolCall.model_validate(c) for c in state["calls"]]
                for index in range(state["index"], len(calls)):
                    state["index"] = index
                    save()
                    result = await ctx.call_tool(calls[index])
                    messages.append(Message.tool(calls[index].id, _tool_content(result)))
                state["phase"] = "model"
            else:
                save()
                value, problem = parse_output(state["candidate"], task.output_type)
                if problem is None:
                    value, problem = await check_output(
                        ctx, value, task.output_type, state["attempt"]
                    )
                if problem is None:
                    return value
                if state["attempt"] >= task.max_repairs:
                    give_up(ctx, problem, state["attempt"])
                state["attempt"] += 1
                state["repairing"] = True
                messages.append(repair_message(ctx, problem, state["attempt"]))
                state["phase"] = "model"
