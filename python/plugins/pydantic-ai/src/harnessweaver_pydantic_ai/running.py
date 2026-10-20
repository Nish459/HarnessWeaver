"""What the ``pydantic_ai.agent`` runner does for each run (see ``runner``).

A run that waits for approval keeps the agent's message history in its
checkpoint. After the approval, the agent continues from that history with every
deferred call approved: the harness's grant lets through the call a human
approved, and asks again about any other (ADR-0021, ADR-0037).
"""

import inspect
import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, JsonValue
from pydantic_ai import DeferredToolRequests, DeferredToolResults, Tool
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.tools import RunContext as AgentContext
from pydantic_ai.toolsets import FunctionToolset

import harnessweaver as hw
from harnessweaver.errors import RunBlocked, RunSuspended, SpecError
from harnessweaver_pydantic_ai.capability import HarnessCapability
from harnessweaver_pydantic_ai.convert import to_json
from harnessweaver_pydantic_ai.model import HarnessModel

if TYPE_CHECKING:
    from harnessweaver_pydantic_ai.runner import AgentRunner

__all__ = ["run_agent"]


def _prompt(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(to_json(value), ensure_ascii=False)


def _variables(value: Any) -> dict[str, Any]:
    data = to_json(value)
    return {**data, "input": data} if isinstance(data, dict) else {"input": data}


def _deferrable(spec: Any) -> list[Any] | None:
    """The agent's output types plus ``DeferredToolRequests``, so approvals can pause it;
    ``None`` when it already has them."""
    items = list(spec) if isinstance(spec, Sequence) and not isinstance(spec, str) else [spec]
    return None if DeferredToolRequests in items else [*items, DeferredToolRequests]


def _executes(run: hw.RunContext, name: str) -> Any:
    async def call(ctx: AgentContext[Any], **arguments: Any) -> JsonValue:
        found = to_json(arguments)
        tool_call = hw.ToolCall(
            id=ctx.tool_call_id or name,
            name=name,
            arguments=found if isinstance(found, dict) else {},
        )
        return (await run.tools.execute(tool_call, run.envelope)).output

    return call


def _task_tools(run: hw.RunContext) -> FunctionToolset[Any] | None:
    """The task's ``tools``, offered to the agent; the capability governs them like its own."""
    names = run.task.tools if run.task is not None else ()
    if not names:
        return None
    tools = [
        Tool.from_schema(
            _executes(run, d.spec.name),
            name=d.spec.name,
            description=d.spec.description,
            json_schema=dict(d.spec.input_schema),
            takes_ctx=True,
        )
        for d in run.tool_specs(names)
    ]
    return FunctionToolset(tools)


async def _options(
    runner: "AgentRunner", run: hw.RunContext, input: Any, capability: HarnessCapability
) -> dict[str, Any]:
    task = run.task
    assert task is not None
    options: dict[str, Any] = {
        "capabilities": [capability],
        "retries": {"output": task.max_repairs},  # the harness owns repair (R5)
    }
    if runner.config.model == "harness":
        options["model"] = HarnessModel(run)
    output_type = _deferrable(runner.agent.output_type)
    if output_type is not None:
        options["output_type"] = output_type
    if task.prompt is not None:
        if run.prompts is None:
            raise SpecError(f"task {task.name} names a prompt, but no prompts are configured")
        options["instructions"] = await run.prompts.render(task.prompt, _variables(input))
    toolset = _task_tools(run)
    if toolset is not None:
        options["toolsets"] = [toolset]
    if runner.deps is not None:
        deps = runner.deps(hw.Session.for_run(run), input)
        options["deps"] = await deps if inspect.isawaitable(deps) else deps
    return options


async def _approved_output(run: hw.RunContext, output: JsonValue) -> JsonValue:
    """An output a human approved at ``output.before``: checked again, then returned."""
    result = await run.check_output(output)
    if isinstance(result.outcome, hw.Retry):
        reason = f"the approved output is invalid: {result.outcome.reason}"
        hook = hw.HookPoint.OUTPUT_BEFORE.value
        raise RunBlocked(reason, hook=hook, code="validation_failed")
    return result.event.output


async def run_agent(
    runner: "AgentRunner",
    run: hw.RunContext,
    input: Any,
    resume: Mapping[str, JsonValue] | None,
) -> Any:
    """Run (or resume) the task's agent inside the harness's run.

    Raises:
        RunInterrupted: When a hook or a budget halts the run, or it waits for approval.
        SpecError: For an agent that defers calls for external execution.
    """
    if run.task is None:
        raise SpecError("the pydantic_ai.agent runner needs a task")
    if resume is not None and "output" in resume:
        return await _approved_output(run, resume["output"])
    capability = HarnessCapability()
    options = await _options(runner, run, input, capability)
    try:
        if resume is None:
            result = await runner.agent.run(_prompt(input), **options)
        else:
            history = ModelMessagesTypeAdapter.validate_python(resume["messages"])
            ids = resume.get("approvals")
            approved = DeferredToolResults(
                approvals={str(i): True for i in ids} if isinstance(ids, list) else {}
            )
            result = await runner.agent.run(
                None, message_history=history, deferred_tool_results=approved, **options
            )
    except RunSuspended:
        run.set_resume_point({"output": capability.output})  # only output.before suspends here
        raise
    output = result.output
    if not isinstance(output, DeferredToolRequests):
        return output.model_dump(mode="json") if isinstance(output, BaseModel) else output
    if output.calls or capability.suspended is None:
        raise SpecError(
            "the agent deferred tool calls for external execution, which the "
            "pydantic_ai.agent runner can't answer"
        )
    messages = ModelMessagesTypeAdapter.dump_python(result.all_messages(), mode="json")
    run.set_resume_point(
        {"messages": to_json(messages), "approvals": [c.tool_call_id for c in output.approvals]}
    )
    raise capability.suspended
