"""Governed tool calls: ``tool.before`` / ``tool.after``, approvals and data labels (S3)."""

import contextlib
from collections.abc import Iterable
from contextlib import AbstractContextManager

from opentelemetry.trace import Span

from harnessweaver.core.context.access import PendingApproval
from harnessweaver.core.context.base import RunContextBase
from harnessweaver.core.errors import (
    RunBlocked,
    RunInterrupted,
    SpecError,
)
from harnessweaver.core.hooks import (
    HookPoint,
    ToolCallEvent,
    ToolResultEvent,
)
from harnessweaver.core.messages import ToolCall
from harnessweaver.core.outcomes import (
    Suspend,
)
from harnessweaver.core.ports import (
    ToolBackend,
    ToolDescription,
)
from harnessweaver.core.state import Grant, call_digest
from harnessweaver.core.tools import ToolInfo, ToolResult


class ToolCalls(RunContextBase):
    """One governed tool call at a time (DESIGNS No. 17)."""

    def _tool_span(self, call: ToolCall, tool: ToolInfo) -> AbstractContextManager[Span | None]:
        if self.telemetry is None:
            return contextlib.nullcontext(None)
        return self.telemetry.tool_span(call, tool)

    async def call_tool(self, call: ToolCall, *, backend: ToolBackend | None = None) -> ToolResult:
        """Make one governed tool call: ``tool.before``, the governor, the tool, ``tool.after``.

        A call a human already approved carries the approval into ``tool.before``,
        with any edited arguments applied (DESIGNS No. 18). The governor checks the
        arguments the middleware leaves (steps 1 to 7) and sanitizes the result
        before ``tool.after`` (step 9, ADR-0025).

        Adapters pass ``backend`` to describe and run a tool that the framework they
        wrap executes itself, such as a Pydantic AI agent's own function. It is
        governed exactly like the run's tools, and during a replay the recording
        answers instead of it (ADR-0035, ADR-0037).

        Raises:
            RunInterrupted: When a hook or a budget halts the run.
        """
        tools = backend or self.tools
        description = tools.describe(call.name)
        if description is None:
            reason = f"tool {call.name!r} isn't registered"
            self.trace.note(
                "harness.tools", reason, hook=HookPoint.TOOL_BEFORE, code="tool_unknown"
            )
            raise RunBlocked(reason, hook=HookPoint.TOOL_BEFORE.value, code="tool_unknown")
        digest = call_digest(call)
        grant = self._grant(HookPoint.TOOL_BEFORE, digest)
        if grant is not None and grant.decision.edited_args is not None:
            call = call.model_copy(update={"arguments": grant.decision.edited_args})
        limit = self.meter.check_tool_call()
        if limit is not None:
            self._budget_stop(HookPoint.TOOL_BEFORE, limit)
        event = ToolCallEvent(
            call=call, tool=description.info, approval=grant.decision if grant else None
        )
        before = await self.emit(HookPoint.TOOL_BEFORE, event)
        if isinstance(before.outcome, Suspend):
            self._ask_about(
                before.event.call,
                description.info,
                digest,
                before.outcome.reason,
                before.outcome.approver_role,
                grant,
            )
        self.halt_on(before)
        call = before.event.call
        if self.governor is not None:
            approval = grant.decision if grant else None
            verdict = await self.governor.authorize(self, call, description, approval)
            if verdict.decision == "block":
                raise RunBlocked(
                    verdict.reason, hook=HookPoint.TOOL_BEFORE.value, code=verdict.code
                )
            if verdict.decision == "require_approval":
                self._ask_about(
                    call, description.info, digest, verdict.reason, verdict.approver_role, grant
                )
                suspend = Suspend(reason=verdict.reason, approver_role=verdict.approver_role)
                raise self.interrupt(HookPoint.TOOL_BEFORE, suspend)
        self._spend(grant)
        self.meter.start_tool_call()
        self._refresh_budget()
        with self._tool_span(call, description.info) as span:
            try:
                runs = self.tools if self.replaying else tools
                result = await runs.execute(call, self._envelope)
            except Exception as exc:
                # The model sees that the tool failed, not why: the message may hold content (R9).
                self.trace.note(
                    "harness.tools",
                    f"tool {call.name} raised {type(exc).__name__}",
                    hook=HookPoint.TOOL_AFTER,
                    code="tool_error",
                )
                result = ToolResult(
                    call_id=call.id, output={"error": type(exc).__name__}, is_error=True
                )
            await self.record("tool", call_digest(call), result=result)
            if self.governor is not None:
                result = await self.governor.sanitize(self, call, description, result)
            after = await self.emit(
                HookPoint.TOOL_AFTER,
                ToolResultEvent(call=call, tool=description.info, result=result),
            )
            if span is not None and self.telemetry is not None:
                self.telemetry.tool_done(span, after.event.result)
        self.halt_on(after)
        final = after.event.result
        if final.untrusted:
            self.mark_untrusted(f"tool:{call.name}")
        if description.info.reads_private_data:
            self.mark_private(f"tool:{call.name}")
        return final

    def _ask_about(
        self,
        call: ToolCall,
        tool: ToolInfo,
        digest: str,
        reason: str,
        role: str | None,
        held: Grant | None,
    ) -> None:
        """Record what the run waits on. An approval the call held didn't answer this ask, so
        the new answer replaces it, keeping the arguments it chose (ADR-0045)."""
        if held is not None:
            self.grants.remove(held)
        self.pending = PendingApproval(
            HookPoint.TOOL_BEFORE,
            reason,
            role,
            digest,
            call=call,
            tool=tool,
            edited_args=held.decision.edited_args if held is not None else None,
        )

    def approval_needed(
        self,
        call: ToolCall,
        reason: str,
        *,
        tool: ToolInfo | None = None,
        approver_role: str | None = None,
    ) -> RunInterrupted | None:
        """The error that pauses the run until a human approves ``call`` (DESIGNS No. 18),
        or ``None`` once one has.

        Adapters raise it for approvals the framework they wrap asks for itself, such
        as a Pydantic AI tool with ``requires_approval=True`` (ADR-0037). The approval
        is matched by the call's name and arguments, so once approved the call passes
        ``tool.before`` without asking again. A run that can't suspend escalates.
        """
        digest = call_digest(call)
        if self._grant(HookPoint.TOOL_BEFORE, digest) is not None:
            return None
        self.trace.note(
            "harness.approvals", reason, hook=HookPoint.TOOL_BEFORE, code="approval_requested"
        )
        self.pending = PendingApproval(
            HookPoint.TOOL_BEFORE,
            reason,
            approver_role,
            digest,
            call=call,
            tool=tool or ToolInfo(name=call.name),
        )
        return self.interrupt(
            HookPoint.TOOL_BEFORE, Suspend(reason=reason, approver_role=approver_role)
        )

    def tool_specs(self, names: Iterable[str]) -> list[ToolDescription]:
        """Describe tools by name.

        Raises:
            SpecError: If one isn't registered.
        """
        found: list[ToolDescription] = []
        for name in names:
            description = self.tools.describe(name)
            if description is None:
                raise SpecError(f"tool {name!r} isn't registered")
            found.append(description)
        return found
