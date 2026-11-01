"""``HarnessCapability``: a Pydantic AI capability that governs an agent run (ADR-0037).

How Pydantic AI's hooks map onto the hook points:

* ``wrap_run`` (around ``before_run``, ``after_run`` and ``on_run_error``): when no
  harness run is active, the agent run becomes one: ``run.start``, ``input.before``
  on the prompt, then ``run.error`` or ``run.end``.
* ``before_model_request``: the model is wrapped, so each request is one governed
  call with ``model.before`` and ``model.after``.
* ``prepare_tools``: a tool with a manifest is offered with the manifest's reviewed
  description and schema (S2).
* ``wrap_tool_execute``: ``tool.before``, the governor, the agent's tool, then
  ``tool.after``.
* ``after_output_process``: ``output.before``; a repair request becomes ``ModelRetry``.
* ``handle_deferred_tool_calls``: a tool with ``requires_approval=True`` asks the
  harness's approvers.

In the ``pydantic_ai.agent`` runner, a call that needs approval is deferred with
``ApprovalRequired``, so the run ends with ``DeferredToolRequests`` and resumes
with ``DeferredToolResults`` once a human approved it. The harness can't resume a
wrapped agent's own run, so there, as in a session, the approval escalates.

One instance governs one run: the runner and ``harness.wrap()`` make a new one
for every run.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

import anyio
from pydantic import BaseModel, JsonValue
from pydantic_ai import ApprovalRequired, DeferredToolRequests, DeferredToolResults, ModelRetry
from pydantic_ai.agent import AbstractAgent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import CallDeferred, ToolFailed, ToolFailedError, ToolRetryError
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.output import OutputContext
from pydantic_ai.run import AgentRunResult
from pydantic_ai.tools import RunContext as AgentContext
from pydantic_ai.tools import ToolDefinition

import harnessweaver as hw
from harnessweaver.adapters import Binding
from harnessweaver.errors import RunBlocked, RunEscalated, RunSuspended, SpecError
from harnessweaver.ports import ToolBackend, ToolDescription
from harnessweaver_pydantic_ai.convert import to_json, user_text
from harnessweaver_pydantic_ai.model import GovernedModel, HarnessModel

__all__ = ["AgentTool", "HarnessCapability"]

_SIGNALS = (ModelRetry, ToolRetryError, ToolFailed, ToolFailedError, CallDeferred, ApprovalRequired)
"""Pydantic AI's control flow from a tool: passed back to the agent, not treated as a failure."""

type Handler = Callable[[Any], Awaitable[Any]]


class AgentTool:
    """One call to a tool the agent runs itself, as a harness ``ToolBackend``.

    The harness's own tools describe it when one of them has its name, so its
    manifest governs it (S2); otherwise it is described from the agent's
    definition, with no manifest. Executing runs the agent's tool.
    """

    def __init__(self, tools: ToolBackend, definition: ToolDefinition, handler: Handler, args: Any):
        self.tools = tools
        self.definition = definition
        self.handler = handler
        self.args = args
        self.sent = to_json(args)
        self.value: Any = None
        self.output: JsonValue = None
        self.signal: Exception | None = None

    def describe(self, name: str) -> ToolDescription | None:
        found = self.tools.describe(name)
        if found is not None or name != self.definition.name:
            return found
        schema = to_json(self.definition.parameters_json_schema)
        spec = hw.ToolSpec(
            name=name,
            description=self.definition.description or "",
            input_schema=schema if isinstance(schema, dict) else {"type": "object"},
        )
        return ToolDescription(hw.ToolInfo(name=name), spec)

    async def execute(self, call: hw.ToolCall, env: hw.Envelope) -> hw.ToolResult:
        # Approved edits reach the tool as JSON values.
        args = self.args if call.arguments == self.sent else dict(call.arguments)
        try:
            self.value = await self.handler(args)
        except _SIGNALS as exc:
            self.signal = exc
            return hw.ToolResult(
                call_id=call.id, output={"error": type(exc).__name__}, is_error=True
            )
        self.output = to_json(self.value)
        return hw.ToolResult(call_id=call.id, output=self.output)


def _retyped(original: Any, value: JsonValue) -> Any:
    """Output middleware's change, in the agent's output type."""
    if isinstance(original, str):
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if isinstance(original, BaseModel):
        return type(original).model_validate(value)
    return value


@dataclass
class HarnessCapability(AbstractCapability[Any]):
    """Governs one Pydantic AI agent run through a harness (see the module doc).

    Args:
        binding: How ``harness.wrap()`` was called. ``None`` in the
            ``pydantic_ai.agent`` runner, which runs it inside the harness's run.
    """

    binding: Binding | None = None
    run: hw.RunContext | None = field(default=None, init=False, repr=False)
    suspended: RunSuspended | None = field(default=None, init=False, repr=False)
    """The approval a deferred call waits for (runner only)."""
    output: JsonValue = field(default=None, init=False, repr=False)
    """The output last sent to ``output.before``."""
    _owns_output: bool = field(default=False, init=False, repr=False)
    _defers: bool = field(default=False, init=False, repr=False)
    _prompt: Any = field(default=None, init=False, repr=False)
    _lock: anyio.Lock = field(default_factory=anyio.Lock, init=False, repr=False)

    def _current(self) -> hw.RunContext:
        if self.run is None:
            raise SpecError(
                "HarnessCapability governs runs started by harness.wrap() or its runner"
            )
        return self.run

    # --- the run ----------------------------------------------------------------------------

    async def wrap_run(self, ctx: AgentContext[Any], *, handler: Any) -> AgentRunResult[Any]:
        outer = hw.current_run()
        if outer is not None:
            # The runner's own run, or a wrapped agent called inside a run or session.
            self.run = outer
            self._owns_output = self._defers = self.binding is None
            return await handler()
        if self.binding is None:
            raise SpecError("the pydantic_ai.agent runner's capability needs a harness run")
        binding = self.binding
        async with binding.harness.session(
            binding.task,
            principal=binding.principal,
            tenant=binding.tenant,
            attributes=binding.attributes,
        ) as session:
            self.run = session.run_context
            self._owns_output = True
            await self._check_prompt(ctx.prompt)
            result: AgentRunResult[Any] = await handler()
            if not isinstance(result.output, DeferredToolRequests):
                self.run.output = to_json(result.output)
            return result

    async def _check_prompt(self, prompt: Any) -> None:
        """``input.before`` on the prompt's text; a redaction replaces the prompt."""
        run = self._current()
        if prompt is None:
            return
        if isinstance(prompt, str):
            checked = await run.check_input(prompt)
            if not isinstance(checked, str):
                raise SpecError("input middleware must keep the prompt a text")
            run.input = checked
            self._prompt = checked if checked != prompt else None
            return
        texts = [user_text([item]) for item in prompt if user_text([item])]
        checked = await run.check_input(list[JsonValue](texts))
        if not (isinstance(checked, list) and all(isinstance(c, str) for c in checked)):
            raise SpecError("input middleware must keep one text per prompt item")
        run.input = checked
        if checked != texts:
            others = [item for item in prompt if not user_text([item])]
            self._prompt = [*checked, *others]

    async def before_node_run(self, ctx: AgentContext[Any], *, node: Any) -> Any:
        if self._prompt is not None and AbstractAgent.is_user_prompt_node(node):
            node = replace(node, user_prompt=self._prompt)
            self._prompt = None
        return node

    # --- model requests ---------------------------------------------------------------------

    async def before_model_request(
        self, ctx: AgentContext[Any], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        run, model = self._current(), request_context.model
        if isinstance(model, HarnessModel | GovernedModel):
            return request_context
        return replace(request_context, model=GovernedModel(model, run))

    # --- tool calls -------------------------------------------------------------------------

    async def prepare_tools(
        self, ctx: AgentContext[Any], tool_defs: list[ToolDefinition]
    ) -> list[ToolDefinition]:
        """Tell the model a governed tool's reviewed definition, not the agent's (S2).

        The digest pins the manifest's definition, so this is what makes it the one
        the model sees, even when a third-party toolset changes its own. Comparing the
        two instead would block ordinary function tools, whose generated schemas differ.
        """
        tools = self._current().tools
        prepared: list[ToolDefinition] = []
        for definition in tool_defs:
            found = tools.describe(definition.name)
            if found is not None and found.manifest is not None:
                definition = replace(
                    definition,
                    description=found.spec.description,
                    parameters_json_schema=dict(found.spec.input_schema),
                )
            prepared.append(definition)
        return prepared

    async def wrap_tool_execute(
        self,
        ctx: AgentContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: Any,
        handler: Handler,
    ) -> Any:
        run = self._current()
        tool = AgentTool(run.tools, tool_def, handler, args)
        sent = tool.sent if isinstance(tool.sent, dict) else {}
        neutral = hw.ToolCall(id=call.tool_call_id, name=call.tool_name, arguments=sent)
        # One governed call at a time: approvals, budgets and labels are per run.
        async with self._lock:
            try:
                if tool_def.kind == "unapproved" and self._defers:
                    # Pydantic AI resumes every deferred call as approved; only the
                    # harness knows which ones a human approved.
                    self._ask(run, neutral)
                result = await run.call_tool(neutral, backend=tool)
            except RunSuspended as exc:
                if not self._defers:
                    raise
                self.suspended = exc
                raise ApprovalRequired(metadata={"harnessweaver": {"reason": str(exc)}}) from None
        if tool.signal is not None:
            raise tool.signal
        return tool.value if result.output == tool.output and not result.is_error else result.output

    async def handle_deferred_tool_calls(
        self, ctx: AgentContext[Any], *, requests: DeferredToolRequests
    ) -> DeferredToolResults | None:
        """In the runner, a tool the agent marks ``requires_approval`` asks the harness's
        approvers; the run resumes with their answer. Elsewhere the app answers it."""
        if not self._defers or self.suspended is not None:
            return None  # one approval at a time; the others are asked on resume
        run = self._current()
        approved: dict[str, bool] = {}
        for part in requests.approvals:
            arguments = to_json(part.args_as_dict())
            call = hw.ToolCall(
                id=part.tool_call_id,
                name=part.tool_name,
                arguments=arguments if isinstance(arguments, dict) else {},
            )
            try:
                self._ask(run, call)
            except RunSuspended as exc:
                self.suspended = exc
                break
            approved[call.id] = True  # a human approved the same call earlier in the run
        return DeferredToolResults(approvals=dict(approved)) if approved else None

    @staticmethod
    def _ask(run: hw.RunContext, call: hw.ToolCall) -> None:
        """Wait for a human unless one approved ``call`` already (``requires_approval``)."""
        found = run.tools.describe(call.name)
        reason = f"the agent asks for approval to call {call.name}"
        error = run.approval_needed(call, reason, tool=found.info if found else None)
        if error is not None:
            raise error

    # --- output -----------------------------------------------------------------------------

    async def after_output_process(
        self, ctx: AgentContext[Any], *, output_context: OutputContext, output: Any
    ) -> Any:
        if not self._owns_output or ctx.partial_output or isinstance(output, DeferredToolRequests):
            return output
        run = self._current()
        sent = to_json(output)
        self.output = sent
        schema = type(output).__name__ if isinstance(output, BaseModel) else None
        result = await run.check_output(sent, attempt=ctx.retry, schema_name=schema)
        if isinstance(result.outcome, hw.Retry):
            raise self._repair(run, result.outcome.reason, ctx.retry)
        final = result.event.output
        return output if final == sent else _retyped(output, final)

    def _repair(self, run: hw.RunContext, problem: str, attempt: int) -> ModelRetry:
        """Ask the model again, or end the run once the task's repairs are used up."""
        task = run.task
        if self._defers and task is not None and attempt >= task.max_repairs:
            reason = f"the output is still invalid after {attempt} repair(s): {problem}"
            run.trace.note(
                "harness.validation",
                reason,
                hook=hw.HookPoint.OUTPUT_BEFORE,
                code="validation_failed",
            )
            hook = hw.HookPoint.OUTPUT_BEFORE.value
            if task.on_failure == "escalate":
                raise RunEscalated(reason, hook=hook, code="validation_failed")
            raise RunBlocked(reason, hook=hook, code="validation_failed")
        run.trace.note(
            "harness.validation",
            f"repair {attempt + 1}: {problem}",
            hook=hw.HookPoint.OUTPUT_BEFORE,
            code="repair",
        )
        return ModelRetry(
            f"Your previous answer was not accepted: {problem}. "
            "Reply again with a corrected answer in the required format."
        )
