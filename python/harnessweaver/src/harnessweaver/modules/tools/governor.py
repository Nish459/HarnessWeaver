"""The tool governor: nine deterministic steps around every tool call (DESIGNS No. 17).

Steps 1 to 7 run in :meth:`Governor.authorize`, on the call's final arguments
after the ``tool.before`` middleware (ADR-0025); step 8 is the transport; step 9
is :meth:`Governor.sanitize`. Every decision is a ``harness.governor`` trace note
with its step and reason (R13).

1. Registry: the tool has a manifest (when ``tools.require_manifest``), is enabled
   for the tenant, and its definition matches its pinned digest (S2).
2. Schema: the arguments match the manifest's ``input_schema``.
3. Policy: the ``PolicyEngine`` (deny blocks), plus approvals the manifest
   (``approval.when``), ``tools.approval_by_risk`` and the task's
   ``approvals.tools`` ask for.
4. Lethal trifecta: untrusted and private data in the run and a tool with egress
   needs approval, or is blocked with ``tools.trifecta: block`` (S3).
5. Limits: ``rate_limit`` per principal and per tenant, held under concurrency.
6. Judge: ``tools.judge``, a guardrail that sees the call, can only tighten (R3).
7. Approval: a call that needs one suspends, unless a human already approved it.
"""

import json
from collections.abc import Mapping
from typing import Final

from harnessweaver.core.decisions import PolicyEffect, tighten
from harnessweaver.core.errors import ExpressionError
from harnessweaver.core.expr import Expression, compile_expression
from harnessweaver.core.guards import GuardAction
from harnessweaver.core.hooks import HookPoint
from harnessweaver.core.jsonschema import validate
from harnessweaver.core.manifests import OutputPolicy, parse_rate
from harnessweaver.core.messages import ToolCall
from harnessweaver.core.outcomes import OutcomeKind
from harnessweaver.core.policy import TOOL_POLICY_VARIABLES, PolicyRequest
from harnessweaver.core.ports import GovernedRun, Guardrail, PolicyEngine, ToolDescription
from harnessweaver.core.runs import ApprovalDecision
from harnessweaver.core.tools import ToolResult, ToolVerdict
from harnessweaver.modules.tools.limits import RateLimiter, Reservation
from harnessweaver.modules.tools.sanitize import sanitize
from harnessweaver.spec.models import ToolsSpec

__all__ = ["Governor"]

_SOURCE: Final = "harness.governor"
_OUTCOMES: Final = {
    "allow": OutcomeKind.CONTINUE,
    "require_approval": OutcomeKind.SUSPEND,
    "block": OutcomeKind.BLOCK,
}


class Governor:
    """The built-in tool governor of one harness.

    Args:
        policy: The spec's policy engine.
        tools: The spec's ``tools`` section.
        approval_rules: Each manifest's compiled ``approval.when``, by tool name.
        task_approvals: Tools each task always asks a human about (``approvals.tools``).
        judge: The ``tools.judge`` guardrail, if any.
    """

    def __init__(
        self,
        *,
        policy: PolicyEngine,
        tools: ToolsSpec,
        approval_rules: Mapping[str, Expression] | None = None,
        task_approvals: Mapping[str, frozenset[str]] | None = None,
        judge: Guardrail | None = None,
    ) -> None:
        self.policy = policy
        self.spec = tools
        self.approval_rules = dict(approval_rules or {})
        self.task_approvals = dict(task_approvals or {})
        self.judge = judge
        self.limiter = RateLimiter()

    async def authorize(
        self,
        ctx: GovernedRun,
        call: ToolCall,
        tool: ToolDescription,
        approval: ApprovalDecision | None,
        *,
        dry_run: bool = False,
    ) -> ToolVerdict:
        """Steps 1 to 7 for one call; the verdict is traced (R13). A dry run gives
        back the rate-limit place it took."""
        reservation: Reservation | None = None
        verdict = self._registry(ctx, tool) or self._schema(call, tool)
        if verdict is None:
            effect, role, reasons, decided = await self._approvals(ctx, call, tool)
            verdict = decided
            if verdict is None:
                reservation, verdict = self._limits(ctx, tool)
            if verdict is None:
                effect, verdict = await self._judge(ctx, call, effect, reasons)
            if verdict is None:
                verdict = self._approval(
                    effect, role or ctx.fallback_approver_role, reasons, approval
                )
        if reservation is not None and (dry_run or verdict.decision != "allow"):
            self.limiter.release(reservation)
        ctx.trace.note(
            _SOURCE,
            verdict.reason,
            hook=HookPoint.TOOL_BEFORE,
            code=verdict.code,
            outcome=_OUTCOMES[verdict.decision],
            details={"tool": call.name, "step": verdict.step, "decision": verdict.decision},
        )
        return verdict

    # --- steps --------------------------------------------------------------------------

    def _registry(self, ctx: GovernedRun, tool: ToolDescription) -> ToolVerdict | None:
        name, manifest = tool.info.name, tool.manifest
        if manifest is None:
            if self.spec.require_manifest:
                return _block(1, "manifest_required", f"tool {name} has no manifest (S2)")
            return None
        if not manifest.spec.enabled:
            return _block(1, "tool_disabled", f"tool {name} is disabled")
        tenants = manifest.spec.tenants
        if tenants and ctx.envelope.tenant not in tenants:
            return _block(1, "tool_not_enabled", f"tool {name} isn't enabled for this tenant")
        if not tool.digest_ok:
            return _block(
                1, "digest_mismatch", f"tool {name}'s definition doesn't match its pinned digest"
            )
        return None

    def _schema(self, call: ToolCall, tool: ToolDescription) -> ToolVerdict | None:
        problems = validate(call.arguments, tool.spec.input_schema)
        if not problems:
            return None
        return _block(2, "schema_invalid", f"tool {call.name} arguments: {'; '.join(problems)}")

    async def _approvals(
        self, ctx: GovernedRun, call: ToolCall, tool: ToolDescription
    ) -> tuple[PolicyEffect, str | None, list[str], ToolVerdict | None]:
        """Steps 3 and 4: the policy engine, the other approval sources, the trifecta."""
        envelope = ctx.envelope
        request = PolicyRequest(
            principal=envelope.principal,
            tenant=envelope.tenant,
            task=envelope.task,
            task_version=envelope.task_version,
            tool=tool.info,
            args=dict(call.arguments),
            labels=envelope.labels,
        )
        decision = await self.policy.decide(request)
        if decision.effect is PolicyEffect.DENY:
            reason = decision.reason or "the policy denies it"
            return decision.effect, None, [], _block(3, "policy_denied", reason)
        effect, reasons = decision.effect, []
        if effect is PolicyEffect.REQUIRE_APPROVAL:
            reasons.append(decision.reason or "the policy requires approval")
        manifest = tool.manifest
        role = manifest.spec.approval.approver_role if manifest and manifest.spec.approval else None
        if manifest is not None and manifest.spec.approval and manifest.spec.approval.when:
            try:
                needed = self._approval_rule(call.name, manifest.spec.approval.when).evaluate_bool(
                    request.variables()
                )
            except ExpressionError:  # can't tell: ask a human rather than let it through
                needed = True
            if needed:
                effect = tighten(effect, PolicyEffect.REQUIRE_APPROVAL)
                reasons.append(f"tool {call.name}'s approval rule")
        if self.spec.approval_by_risk.get(tool.info.risk) == "required":
            effect = tighten(effect, PolicyEffect.REQUIRE_APPROVAL)
            reasons.append(f"{tool.info.risk.value}-risk tools need approval")
        if call.name in self.task_approvals.get(envelope.task or "", frozenset()):
            effect = tighten(effect, PolicyEffect.REQUIRE_APPROVAL)
            reasons.append(f"task {envelope.task} asks before {call.name}")
        labels = envelope.labels
        if labels.untrusted_seen and labels.private_seen and tool.info.egress:
            reason = (
                f"tool {call.name} can send data out after untrusted and private data "
                "entered the run (lethal trifecta, S3)"
            )
            if self.spec.trifecta == "block":
                return effect, role, reasons, _block(4, "trifecta", reason)
            effect = tighten(effect, PolicyEffect.REQUIRE_APPROVAL)
            reasons.append(reason)
        return effect, role, reasons, None

    def _approval_rule(self, name: str, source: str) -> Expression:
        """The tool's compiled ``approval.when``: from load for manifest files, compiled
        on first use for tools given in code."""
        rule = self.approval_rules.get(name)
        if rule is None or rule.source != source:
            rule = compile_expression(source, declared=TOOL_POLICY_VARIABLES)
            self.approval_rules[name] = rule
        return rule

    def _limits(
        self, ctx: GovernedRun, tool: ToolDescription
    ) -> tuple[Reservation | None, ToolVerdict | None]:
        manifest = tool.manifest
        limit = manifest.spec.rate_limit if manifest is not None else None
        if limit is None:
            return None, None
        envelope, name = ctx.envelope, tool.info.name
        wanted: list[tuple[tuple[str, str, str], int, float]] = []
        if limit.per_principal is not None:
            count, window = parse_rate(limit.per_principal)
            wanted.append(((name, "principal", envelope.principal.id), count, window))
        if limit.per_tenant is not None:
            count, window = parse_rate(limit.per_tenant)
            wanted.append(((name, "tenant", envelope.tenant), count, window))
        reservation = self.limiter.acquire(wanted, ctx.clock.now().timestamp())
        if reservation is None:
            return None, _block(5, "rate_limited", f"tool {name} is over its rate limit")
        return reservation, None

    async def _judge(
        self, ctx: GovernedRun, call: ToolCall, effect: PolicyEffect, reasons: list[str]
    ) -> tuple[PolicyEffect, ToolVerdict | None]:
        if self.judge is None:
            return effect, None
        content = json.dumps({"tool": call.name, "args": call.arguments}, sort_keys=True)
        try:
            judged = await self.judge.check(content, ctx.envelope)
        except Exception as exc:  # a failing judge can't let a call through, nor stop it alone
            reasons.append(f"the judge failed ({type(exc).__name__})")
            return tighten(effect, PolicyEffect.REQUIRE_APPROVAL), None
        if judged.action is GuardAction.BLOCK:
            return PolicyEffect.DENY, _block(
                6, "judge_blocked", judged.reason or "the judge blocks it"
            )
        if judged.action in (GuardAction.REQUIRE_APPROVAL, GuardAction.ESCALATE):
            reasons.append(judged.reason or "the judge asks for approval")
            return tighten(effect, PolicyEffect.REQUIRE_APPROVAL), None
        return effect, None

    @staticmethod
    def _approval(
        effect: PolicyEffect,
        role: str | None,
        reasons: list[str],
        approval: ApprovalDecision | None,
    ) -> ToolVerdict:
        if effect is not PolicyEffect.REQUIRE_APPROVAL:
            return ToolVerdict(decision="allow", step=7, reason="allowed")
        if approval is not None and approval.decision != "reject":
            # An approval given for another step's ask counts only if the approver also holds
            # the role this step needs (ADR-0045).
            if role is None or approval.approver.has_role(role):
                reason = f"approved by {approval.approver.id}"
                return ToolVerdict(decision="allow", step=7, code="approved", reason=reason)
            reasons = [*reasons, f"{approval.approver.id} approved without the role {role!r}"]
        return ToolVerdict(
            decision="require_approval",
            step=7,
            code="approval_required",
            reason="; ".join(reasons),
            approver_role=role,
        )

    # --- step 9 ---------------------------------------------------------------------------

    async def sanitize(
        self, ctx: GovernedRun, call: ToolCall, tool: ToolDescription, result: ToolResult
    ) -> ToolResult:
        """Step 9: sanitizers, truncation and the untrusted label, traced when they change it."""
        manifest = tool.manifest
        policy = manifest.spec.output if manifest is not None else OutputPolicy()
        limit = policy.max_bytes or self.spec.max_output_bytes
        cleaned, done = await sanitize(result, policy, limit, ctx.envelope)
        if done:
            ctx.trace.note(
                _SOURCE,
                f"tool {call.name} output: {', '.join(done)}",
                hook=HookPoint.TOOL_AFTER,
                code="output_sanitized",
                details={"tool": call.name, "step": 9},
            )
        return cleaned


def _block(step: int, code: str, reason: str) -> ToolVerdict:
    return ToolVerdict(decision="block", step=step, code=code, reason=reason)
