"""Replaying a recorded run against the current code and spec (ADR-0035).

A run recorded with ``state.record: true`` kept every model answer, tool result
and human approval it got. A replay runs the task again on a copy of the harness
whose model answers from the recording, in order, and whose tools return the
recorded results of matching calls and never execute. Recorded approvals answer
the approvals the replay asks for again. The copy keeps its runs in memory, so
a replay leaves the state store as it was. The report compares statuses,
outputs and the decisions in the two traces.
"""

from collections.abc import Sequence
from difflib import SequenceMatcher

from opentelemetry import metrics, trace

from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import NotFound, ProviderError, SpecError
from harnessweaver.core.messages import ModelRequest, ModelResponse, ToolCall
from harnessweaver.core.outcomes import OutcomeKind
from harnessweaver.core.ports import ToolBackend, ToolDescription
from harnessweaver.core.replay import ReplayReport, TraceChange
from harnessweaver.core.runs import RunStatus
from harnessweaver.core.state import RecordedCall, call_digest, request_digest
from harnessweaver.core.telemetry import Telemetry
from harnessweaver.core.tools import ToolResult
from harnessweaver.core.trace import TraceEvent, TraceKind
from harnessweaver.harness.checks import ChecksMixin
from harnessweaver.modules.evals.values import json_equal
from harnessweaver.modules.state import MemoryStateStore

__all__ = ["RecordedModel", "RecordedTools", "ReplayMixin", "trace_changes"]


class RecordedModel:
    """A model provider that answers from a recording, in order; it never calls out."""

    def __init__(self, calls: Sequence[RecordedCall]) -> None:
        self.answers = [c for c in calls if c.kind == "model" and c.response is not None]
        self.used = 0
        self.changed = 0

    async def generate(self, request: ModelRequest, env: Envelope) -> ModelResponse:
        if self.used >= len(self.answers):
            raise ProviderError("the recording has no more model answers")
        answer = self.answers[self.used]
        self.used += 1
        if answer.digest != request_digest(request):
            self.changed += 1
        assert answer.response is not None
        return answer.response


class RecordedTools:
    """Tools described as the harness describes them, answered from a recording.

    A call gets the result recorded for the same name and arguments, once; a call
    the recording doesn't have fails like a tool that raised. Nothing executes.
    """

    def __init__(self, inner: ToolBackend | None, calls: Sequence[RecordedCall]) -> None:
        self.inner = inner
        self.results = [c for c in calls if c.kind == "tool" and c.result is not None]
        self.used: set[int] = set()
        self.missing = 0

    def describe(self, name: str) -> ToolDescription | None:
        return self.inner.describe(name) if self.inner is not None else None

    async def execute(self, call: ToolCall, env: Envelope) -> ToolResult:
        digest = call_digest(call)
        for index, recorded in enumerate(self.results):
            if index not in self.used and recorded.digest == digest:
                self.used.add(index)
                assert recorded.result is not None
                return recorded.result.model_copy(update={"call_id": call.id})
        self.missing += 1
        raise ProviderError(f"the recording has no result for this call to {call.name}")


def _decisions(events: Sequence[TraceEvent]) -> list[TraceEvent]:
    """Outcomes other than a plain continue, and coded notes."""
    return [
        e
        for e in events
        if (
            e.kind in (TraceKind.OUTCOME, TraceKind.FAILURE)
            and (e.outcome is not OutcomeKind.CONTINUE or e.modified or e.reason)
        )
        or (e.kind is TraceKind.NOTE and e.code is not None)
    ]


def _change(change: str, event: TraceEvent) -> TraceChange:
    return TraceChange.model_validate(
        {
            "change": change,
            "hook": event.hook,
            "source": event.source,
            "outcome": event.outcome,
            "code": event.code,
            "reason": event.reason,
        }
    )


def trace_changes(
    original: Sequence[TraceEvent], replayed: Sequence[TraceEvent]
) -> tuple[TraceChange, ...]:
    """The decisions only one of two traces has, matched by hook, source, outcome and code."""
    before, after = _decisions(original), _decisions(replayed)

    def key(e: TraceEvent) -> tuple[object, ...]:
        return (e.hook, e.source, e.outcome, e.code)

    matcher = SequenceMatcher(a=[key(e) for e in before], b=[key(e) for e in after], autojunk=False)
    changes: list[TraceChange] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            changes += [_change("removed", e) for e in before[i1:i2]]
        if tag in ("replace", "insert"):
            changes += [_change("added", e) for e in after[j1:j2]]
    return tuple(changes)


def _quiet() -> Telemetry:
    # A replay is a check, not production traffic: it exports no spans or metrics.
    return Telemetry(
        tracer_provider=trace.NoOpTracerProvider(), meter_provider=metrics.NoOpMeterProvider()
    )


class ReplayMixin(ChecksMixin):
    """``replay``."""

    async def replay(self, run_id: str) -> ReplayReport:
        """Run a recorded run's task again against the current code and spec.

        The model answers and tool results come from the recording, so nothing
        calls out and no tool executes; recorded approvals answer the approvals
        the replay asks for. ``harnessweaver replay`` prints the report.

        Raises:
            NotFound: For an unknown run.
            SpecError: For a run that has no recording or no result yet, or whose
                task the spec no longer defines.
        """
        record = await self._state.get_run(run_id)
        if record is None:
            raise NotFound(f"no run {run_id}", run_id=run_id)
        if record.task is None or record.task not in self._tasks:
            raise SpecError(f"run {run_id} didn't run a task this spec defines", run_id=run_id)
        if record.result is None:
            raise SpecError(f"run {run_id} has no result yet", run_id=run_id)
        calls = await self._state.recording(run_id)
        if not calls:
            raise SpecError(
                f"run {run_id} has no recording; set state.record: true to record runs",
                run_id=run_id,
            )
        model, tools = RecordedModel(calls), RecordedTools(self._tools, calls)
        twin = self._rebuilt(model=model, state=MemoryStateStore(), telemetry=_quiet())
        twin._tools = tools  # every call gets a recorded result; none executes
        result = await twin.run(
            record.task,
            record.input,
            principal=record.envelope.principal,
            tenant=record.tenant,
            attributes=record.envelope.attributes,
        )
        approvals = [c for c in calls if c.kind == "approval" and c.decision is not None]
        while result.status is RunStatus.AWAITING_APPROVAL and result.approval is not None:
            checkpoint = await twin._state.get_checkpoint(result.run_id)
            found = next(
                (
                    c
                    for c in approvals
                    if checkpoint is not None
                    and c.hook == checkpoint.approval_hook
                    and c.digest == checkpoint.approval_digest
                ),
                None,
            )
            if found is None or found.decision is None:
                break
            approvals.remove(found)
            answer = found.decision
            result = await twin.approve(
                result.run_id,
                result.approval.approval_id,
                answer.decision,
                approver=answer.approver,
                edited_args=answer.edited_args,
                reason=answer.reason,
            )
        original = record.result
        return ReplayReport(
            run_id=run_id,
            task=record.task,
            original=original,
            replayed=result,
            same_status=original.status is result.status,
            same_output=json_equal(original.output, result.output),
            changes=trace_changes(original.trace, result.trace),
            model_answers=len(model.answers),
            model_answers_used=model.used,
            changed_requests=model.changed,
            missing_tool_results=tools.missing,
        )
