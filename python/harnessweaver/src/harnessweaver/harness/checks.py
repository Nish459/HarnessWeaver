"""Asking a harness about itself without running anything: a tool call's verdict, a
policy decision, a task's output schema, and the online samples it kept."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import JsonValue

from harnessweaver.core.decisions import PolicyEffect
from harnessweaver.core.envelope import Clock, Envelope, Labels, Principal
from harnessweaver.core.evals import OnlineSample
from harnessweaver.core.messages import ToolCall
from harnessweaver.core.policy import PolicyDecision, PolicyRequest
from harnessweaver.core.tools import ToolVerdict
from harnessweaver.core.trace import RunTrace
from harnessweaver.harness.build import output_schema
from harnessweaver.harness.wrap import WrapMixin

__all__ = ["ChecksMixin"]


@dataclass(slots=True)
class _DryRun:
    """The run a dry-run verdict is decided for (``GovernedRun``)."""

    trace: RunTrace
    envelope: Envelope

    @property
    def clock(self) -> Clock:
        return self.envelope.clock


class ChecksMixin(WrapMixin):
    """``authorize``, ``decide_policy``, ``output_type``, ``output_schema`` and ``samples``."""

    async def authorize(
        self,
        tool: str,
        args: Mapping[str, JsonValue] | None = None,
        *,
        principal: Principal | str = "anonymous",
        tenant: str = "default",
        task: str | None = None,
        labels: Labels | None = None,
    ) -> ToolVerdict:
        """What the governor would decide about one tool call, without running it.

        Steps 1 to 7 run as for a real call (DESIGNS No. 17) on a run with this
        principal, tenant, task and labels, as a dry run: a rate limit isn't used
        up and nothing is approved or executed. An approval's ``approver_role``
        falls back to the task's and then the spec's ``approvals.approver_role``, as
        the request a real run makes would. ``harnessweaver policy test`` is built
        on this.

        Raises:
            NotFound: For a task the spec doesn't define.
        """
        entry = self._task(task) if task is not None else None
        envelope = Envelope.new(
            tenant=tenant,
            principal=principal,
            task=task,
            task_version=entry.info.version if entry is not None else None,
            clock=self._clock,
        )
        if labels is not None:
            envelope = envelope.with_labels(labels)
        description = self._tools.describe(tool) if self._tools is not None else None
        if description is None:
            return ToolVerdict(
                decision="block",
                step=1,
                code="tool_unknown",
                reason=f"tool {tool!r} isn't registered",
            )
        if self._governor is None:  # pragma: no cover - every built harness has a governor
            return ToolVerdict(decision="allow", step=7, reason="no governor")
        call = ToolCall(id="dry_run", name=tool, arguments=dict(args or {}))
        run = _DryRun(RunTrace(self._clock), envelope)
        verdict = await self._governor.authorize(run, call, description, None, dry_run=True)
        if verdict.decision != "require_approval":
            return verdict
        role = self._approver_role(entry, verdict.approver_role)
        return verdict.model_copy(update={"approver_role": role})

    async def decide_policy(self, request: PolicyRequest) -> PolicyDecision:
        """What the spec's policy engine answers, alone: ``policy.rules`` combined as
        every engine combines them (ADR-0025), without the governor's other steps.

        ``authorize`` gives the governor's full verdict on a tool call;
        ``POST /v1/policy/evaluate`` on harnessd is built on this.
        """
        if self._policy is None:  # pragma: no cover - every built harness has a policy engine
            return PolicyDecision(effect=PolicyEffect.ALLOW, reason="no policy engine")
        return await self._policy.decide(request)

    def output_type(self, task: str) -> type[Any] | None:
        """The type a task's output is parsed into, or ``None`` when the task returns
        whatever the model says.

        Raises:
            NotFound: For a task the spec doesn't define.
        """
        return self._task(task).info.output_type

    def output_schema(self, task: str) -> dict[str, JsonValue] | None:
        """The JSON Schema of a task's output as run results carry it, or ``None`` when
        the task returns whatever the model says.

        Raises:
            NotFound: For a task the spec doesn't define.
        """
        return output_schema(self._task(task).info.output_type)

    async def samples(self, task: str | None = None) -> list[OnlineSample]:
        """The production runs ``evals.online`` sampled and graded, oldest first
        (``harnessweaver eval report``)."""
        return await self._state.samples(task)
