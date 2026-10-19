"""Governed checks on a run's input, routing, context, output and approvals."""

from collections.abc import Iterable

from pydantic import JsonValue

from harnessweaver.core.bus import HookResult
from harnessweaver.core.context.access import PendingApproval
from harnessweaver.core.context.base import RunContextBase
from harnessweaver.core.decisions import Decision, DecisionRequest, PolicyEffect
from harnessweaver.core.errors import RunBlocked, RunEscalated
from harnessweaver.core.hooks import (
    ApprovalResolvedEvent,
    ContextEvent,
    HookPoint,
    InputEvent,
    OutputEvent,
    RouteEvent,
)
from harnessweaver.core.outcomes import (
    OutcomeKind,
    Suspend,
)
from harnessweaver.core.policy import PolicyRequest
from harnessweaver.core.retrieval import ContextItem
from harnessweaver.core.runs import ApprovalDecision, ApprovalRequest
from harnessweaver.core.state import output_digest


class StepChecks(RunContextBase):
    """``input.before``, ``route.decide``, ``context.after``, ``output.before`` and
    ``approval.resolved`` (DESIGNS No. 7)."""

    async def authorize_run(self) -> None:
        """Ask the policy engine whether this run may start (``run.start`` rules, ADR-0025).

        A decision a rule made is traced (R13); a run no rule restricts goes ahead.

        Raises:
            RunBlocked: When a rule denies the run.
            RunEscalated: When a rule asks for approval: a run can't wait before it starts.
        """
        if self.policy is None:
            return
        envelope = self._envelope
        request = PolicyRequest(
            hook="run.start",
            principal=envelope.principal,
            tenant=envelope.tenant,
            task=envelope.task,
            task_version=envelope.task_version,
            labels=envelope.labels,
        )
        decision = await self.policy.decide(request)
        if decision.rule is None and decision.effect is PolicyEffect.ALLOW:
            return
        reason = decision.reason or f"the policy says {decision.effect.value}"
        kind = {
            PolicyEffect.ALLOW: OutcomeKind.CONTINUE,
            PolicyEffect.REQUIRE_APPROVAL: OutcomeKind.ESCALATE,
            PolicyEffect.DENY: OutcomeKind.BLOCK,
        }[decision.effect]
        details: dict[str, JsonValue] = {"effect": decision.effect.value, "rule": decision.rule}
        hook = HookPoint.RUN_START
        self.trace.note("harness.policy", reason, hook=hook, outcome=kind, details=details)
        if decision.effect is PolicyEffect.DENY:
            raise RunBlocked(reason, hook=hook.value, code="policy_denied")
        if decision.effect is PolicyEffect.REQUIRE_APPROVAL:
            raise RunEscalated(reason, hook=hook.value, code="policy_requires_approval")

    async def check_input(self, value: JsonValue) -> JsonValue:
        """Fire ``input.before``; return the (possibly redacted) input."""
        result = await self.emit(HookPoint.INPUT_BEFORE, InputEvent(input=value))
        self.halt_on(result)
        return result.event.input

    async def decide(self, request: DecisionRequest, *, default: str | None = None) -> Decision:
        """Fire ``route.decide``. Without an answer, use ``default`` or abstain."""
        result = await self.emit(HookPoint.ROUTE_DECIDE, RouteEvent(request=request))
        self.halt_on(result)
        decision = result.event.decision
        if decision is None:
            decision = (
                Decision.default(default, reason="no stage decided")
                if default is not None
                else Decision.abstain(reason="no stage decided")
            )
        details: dict[str, JsonValue] = {"router": request.router, "kind": decision.kind.value}
        if decision.choice is not None:
            details["choice"] = decision.choice
        if decision.confidence is not None:
            details["confidence"] = decision.confidence
        if decision.stage is not None:
            details["stage"] = decision.stage
        self.trace.note(
            "harness.decision",
            decision.reason or decision.kind.value,
            hook=HookPoint.ROUTE_DECIDE,
            details=details,
        )
        if self.telemetry is not None:
            self.telemetry.decision(request, decision)
        return decision

    async def context_after(
        self, source: str, items: Iterable[ContextItem], *, query: str | None = None
    ) -> tuple[ContextItem, ...]:
        """Fire ``context.after`` on retrieved items; label the run if any are untrusted."""
        event = ContextEvent(source=source, query=query, items=tuple(items))
        result = await self.emit(HookPoint.CONTEXT_AFTER, event)
        self.halt_on(result)
        kept = result.event.items
        if any(item.untrusted for item in kept):
            self.mark_untrusted(f"context:{source}")
        return kept

    async def check_output(
        self, output: JsonValue, *, attempt: int = 0, schema_name: str | None = None
    ) -> HookResult[OutputEvent]:
        """Fire ``output.before``. ``Retry`` is returned for the caller to repair.

        Raises:
            RunInterrupted: For ``Block``, ``Escalate`` or ``Suspend``.
        """
        digest = output_digest(output)
        grant = self._grant(HookPoint.OUTPUT_BEFORE, digest)
        event = OutputEvent(
            output=output,
            attempt=attempt,
            schema_name=schema_name,
            approval=grant.decision if grant else None,
        )
        result = await self.emit(HookPoint.OUTPUT_BEFORE, event)
        if isinstance(result.outcome, Suspend):
            self.pending = PendingApproval(
                HookPoint.OUTPUT_BEFORE,
                result.outcome.reason,
                result.outcome.approver_role,
                digest,
            )
        self.halt_on(result, allow_retry=True)
        return result

    async def approval_resolved(self, request: ApprovalRequest, decision: ApprovalDecision) -> None:
        """Fire ``approval.resolved``; a halting outcome ends the run."""
        result = await self.emit(
            HookPoint.APPROVAL_RESOLVED, ApprovalResolvedEvent(request=request, decision=decision)
        )
        self.halt_on(result)
