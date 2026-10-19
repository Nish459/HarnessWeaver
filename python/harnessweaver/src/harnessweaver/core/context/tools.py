"""Governed tool calls: ``tool.before`` / ``tool.after``, approvals and data labels (S3)."""

import contextlib
from collections.abc import Iterable
from contextlib import AbstractContextManager

from opentelemetry.trace import Span

from harnessweaver.core.context.access import PendingApproval
from harnessweaver.core.context.base import RunContextBase
from harnessweaver.core.errors import (
    RunBlocked,
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
    ToolDescription,
)
from harnessweaver.core.state import call_digest
from harnessweaver.core.tools import ToolInfo, ToolResult


class ToolCalls(RunContextBase):
    """One governed tool call at a time (DESIGNS No. 17)."""

    def _tool_span(self, call: ToolCall, tool: ToolInfo) -> AbstractContextManager[Span | None]:
        if self.telemetry is None:
            return contextlib.nullcontext(None)
        return self.telemetry.tool_span(call, tool)

    async def call_tool(self, call: ToolCall) -> ToolResult:
        """Make one governed tool call: ``tool.before``, the tool, ``tool.after``.

        A call a human already approved carries the approval into ``tool.before``,
        with any edited arguments applied (DESIGNS No. 18).

        Raises:
            RunInterrupted: When a hook or a budget halts the run.
        """
        description = self.tools.describe(call.name)
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
            self.pending = PendingApproval(
                HookPoint.TOOL_BEFORE,
                before.outcome.reason,
                before.outcome.approver_role,
                digest,
                call=before.event.call,
                tool=description.info,
            )
        self.halt_on(before)
        call = before.event.call
        self.meter.start_tool_call()
        self._refresh_budget()
        with self._tool_span(call, description.info) as span:
            try:
                result = await self.tools.execute(call, self._envelope)
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
