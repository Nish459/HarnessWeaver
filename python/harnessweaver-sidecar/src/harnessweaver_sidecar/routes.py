"""harnessd's ``/v1`` routes (ADR-0038). Each maps onto one ``Harness`` or ``Session``
call, so the sidecar decides exactly what an in-process harness would.

Two kinds of route:

* **Checks** (``guards/{stage}``, ``decisions/{router}``, ``tools/{name}/sanitize``,
  ``validate``) run as a one-step session: ``run.start`` and its policy rules,
  the one governed call, then ``run.end``. The answer is that session's
  ``RunResult``, whose ``output`` is what the check returned (the redacted input,
  the decision, the kept items, the sanitized result); a block or a failure is
  its ``status`` and ``error``, and its trace says why (R13).
* **Lookups and runs** (``spec``, ``hooks``, ``policy/evaluate``,
  ``tools/{name}/authorize``, ``guards/providers/{name}:check``, ``runs``,
  ``evals/run``) call the harness directly and answer with its own contract.
"""

import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic_core import to_jsonable_python

from harnessweaver import Harness, Session
from harnessweaver.contracts import API_VERSION
from harnessweaver.core.errors import ErrorInfo, HarnessError, NotFound, SpecError, ValidationFailed
from harnessweaver.core.evals import SuiteResult
from harnessweaver.core.guards import GuardResult
from harnessweaver.core.hooks import HookPoint, ToolResultEvent
from harnessweaver.core.ids import new_id
from harnessweaver.core.messages import ToolCall
from harnessweaver.core.policy import PolicyDecision, PolicyRequest
from harnessweaver.core.ports import Guardrail
from harnessweaver.core.results import RunResult
from harnessweaver.core.sidecar import (
    ApprovalAnswer,
    AuthorizeRequest,
    Caller,
    CheckStage,
    DecideRequest,
    EvalRunRequest,
    HookEntry,
    ProviderCheck,
    RunRequest,
    SanitizeRequest,
    SpecInfo,
    StageCheck,
    ValidateRequest,
)
from harnessweaver.core.tools import ToolResult, ToolVerdict
from harnessweaver_sidecar.auth import authorized

__all__ = ["ERRORS", "router"]

ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorInfo, "description": description}
    for status, description in [
        (400, "The spec or the request names something invalid"),
        (401, "A valid bearer token is required (S6)"),
        (404, "No such task, run, approval, tool or suite"),
        (413, "The request body is over harnessd's limit"),
        (422, "The request body doesn't match its schema"),
        (502, "A provider failed"),
    ]
}
"""The error answers every protected route can give; each body is an ``ErrorInfo``."""

router = APIRouter(prefix="/v1", dependencies=[Depends(authorized)], responses=ERRORS)


def _harness(request: Request) -> Harness:
    """The harness the app was created with (``create_app``)."""
    harness: Harness = request.app.state.harness
    return harness


Served = Annotated[Harness, Depends(_harness)]
"""A route parameter that receives the served harness."""


async def one_step(
    harness: Harness, caller: Caller, step: Callable[[Session], Awaitable[Any]]
) -> RunResult:
    """Run ``step`` as a one-step session for ``caller``; what it returns becomes the
    run's output.

    A taxonomy error inside the session (a block, an escalation, a failed check)
    is not an HTTP error: the session records it as the run's status and error,
    so it is suppressed here and answered in the ``RunResult``. Anything else is
    a bug, recorded by the session too, and reaches the client as a 500.
    """
    session = harness.session(caller.task, principal=caller.principal, tenant=caller.tenant)
    with contextlib.suppress(HarnessError):
        async with session as s:
            value = await step(s)
            s.run_context.output = to_jsonable_python(value)
    assert session.result is not None  # set by the session, even when run.start halts it
    return session.result


# --- lookups --------------------------------------------------------------------------------


@router.get("/spec")
async def spec(harness: Served) -> SpecInfo:
    """The effective spec harnessd serves: every layer merged, locks and bounds applied."""
    effective = harness.spec
    return SpecInfo(
        name=harness.name,
        api_version=API_VERSION,
        tasks=tuple(harness.tasks),
        level=effective.level.level.value,
        required_level=effective.level.required.value,
        spec=effective.spec.model_dump(mode="json", by_alias=True),
    )


@router.get("/hooks")
async def hooks(harness: Served, task: str | None = None) -> dict[str, list[HookEntry]]:
    """The middleware on every hook point, in the order it runs (``harnessweaver hooks``)."""
    return {
        hook.value: [
            HookEntry(
                name=r.name,
                band=r.band.value,
                fail_mode=r.fail_mode,
                timeout_seconds=r.timeout.total_seconds() if r.timeout is not None else None,
            )
            for r in chain
        ]
        for hook, chain in harness.hooks(task).items()
    }


@router.post("/policy/evaluate")
async def evaluate_policy(body: PolicyRequest, harness: Served) -> PolicyDecision:
    """What the policy engine alone decides (``policy.rules``, ADR-0025)."""
    return await harness.decide_policy(body)


@router.post("/tools/{name}/authorize")
async def authorize(name: str, body: AuthorizeRequest, harness: Served) -> ToolVerdict:
    """The governor's verdict on a call (steps 1 to 7) as a dry run: nothing executes,
    no rate limit is used up (ADR-0036)."""
    return await harness.authorize(
        name,
        body.args,
        principal=body.principal,
        tenant=body.tenant,
        task=body.task,
        labels=body.labels,
    )


@router.post("/guards/providers/{name}:check")
async def check_provider(name: str, body: ProviderCheck, request: Request) -> GuardResult:
    """Run one guardrail provider: what a ``where: sidecar`` guard asks (DESIGNS No. 24).

    The provider must be allowed by the served spec's ``plugins.allow`` (S8).
    Built providers are kept per name and settings, since heavy ones (a PII
    model, a classifier) are slow to build.
    """
    harness: Harness = request.app.state.harness
    cache: dict[str, Guardrail] = request.app.state.providers
    key = json.dumps([name, body.settings, body.stage], sort_keys=True)
    # Unbounded, but keyed by spec settings, which a fleet of specs keeps small.
    provider = cache.get(key)
    if provider is None:
        info = harness.registry.provider("Guardrail", name)
        if body.stage is not None and info.stages and body.stage not in info.stages:
            supported = ", ".join(info.stages)
            raise SpecError(
                f"guard {name} can't run at stage {body.stage!r}; it supports {supported}"
            )
        provider = cache[key] = info.build(body.settings)
    return await provider.check(body.content, body.envelope)


# --- checks: one-step sessions ---------------------------------------------------------------


@router.post("/guards/{stage}")
async def check_stage(stage: CheckStage, body: StageCheck, harness: Served) -> RunResult:
    """Run a stage's hook the way a session does: ``input`` fires ``input.before``,
    ``context`` fires ``context.after`` (ACLs re-checked first, ADR-0030), and
    ``output`` fires ``output.before``. Every guard and middleware at that hook runs."""

    async def step(s: Session) -> Any:
        if stage == "input":
            return await s.guard("input", body.content)
        if stage == "output":
            return await s.validate("output", body.content)
        if body.source is None:
            raise ValidationFailed("a context check names its source")
        return await s.context(body.source).check(body.items, query=body.query)

    return await one_step(harness, body, step)


@router.post("/decisions/{router}")
async def decide(router: str, body: DecideRequest, harness: Served) -> RunResult:
    """Ask a router to choose (``route.decide``); the output is the ``Decision``."""

    async def step(s: Session) -> Any:
        return await s.decide(
            router,
            text=body.text,
            options=body.options,
            state=dict(body.state),
            default=body.default,
        )

    return await one_step(harness, body, step)


@router.post("/tools/{name}/sanitize")
async def sanitize(name: str, body: SanitizeRequest, harness: Served) -> RunResult:
    """What the harness does to a tool's result before a model sees it: the
    governor's step 9 (sanitizers, truncation, the untrusted label), then
    ``tool.after`` with its ``tool_result`` guards. The output is the ``ToolResult``."""

    async def step(s: Session) -> Any:
        ctx = s.run_context
        description = ctx.tools.describe(name)
        if description is None:
            raise NotFound(f"tool {name!r} isn't registered")
        call = ToolCall(id=new_id("call"), name=name, arguments=body.arguments)
        result = ToolResult(call_id=call.id, output=body.output, is_error=body.is_error)
        if ctx.governor is not None:
            result = await ctx.governor.sanitize(ctx, call, description, result)
        event = ToolResultEvent(call=call, tool=description.info, result=result)
        after = await ctx.emit(HookPoint.TOOL_AFTER, event)
        ctx.halt_on(after)
        return after.event.result

    return await one_step(harness, body, step)


@router.post("/validate")
async def validate(body: ValidateRequest, harness: Served) -> RunResult:
    """Check a final output against a task: parsed into its output type, then
    ``output.before`` (guards and ``validation.rules``). A repair request ends the
    run ``failed`` with a ``validation_failed`` error naming the problem."""
    output_type = harness.output_type(body.task)

    async def step(s: Session) -> Any:
        return await s.validate("output", body.output, output=output_type)

    return await one_step(harness, body, step)


# --- runs and evals --------------------------------------------------------------------------


@router.post("/runs")
async def start_run(body: RunRequest, harness: Served) -> RunResult:
    """Run a task to the end, or until it waits for approval (``harness.run``)."""
    return await harness.run(
        body.task,
        body.input,
        principal=body.principal,
        tenant=body.tenant,
        idempotency_key=body.idempotency_key,
        budget=body.budget,
        attributes=body.attributes,
    )


@router.get("/runs/{run_id}")
async def get_run(run_id: str, harness: Served) -> RunResult:
    """The latest state of a run, check sessions included."""
    return await harness.result(run_id)


@router.post("/runs/{run_id}/approvals/{approval_id}")
async def answer_approval(
    run_id: str, approval_id: str, body: ApprovalAnswer, harness: Served
) -> RunResult:
    """Answer a pending approval and continue the run (DESIGNS No. 18)."""
    return await harness.approve(
        run_id,
        approval_id,
        body.decision,
        approver=body.approver,
        edited_args=body.edited_args,
        reason=body.reason,
    )


@router.post("/evals/run")
async def run_evals(body: EvalRunRequest, harness: Served) -> SuiteResult:
    """Run an eval suite: one given in the request, or a file the spec's ``evals``
    lists. Only listed files can be named, so a client can't make harnessd read
    any other file."""
    if body.dataset is not None:
        return await harness.evaluate(body.dataset)
    listed = {file for files in harness.spec.spec.evals.suites().values() for file in files}
    if body.file not in listed:
        raise NotFound(f"{body.file!r} isn't one of the spec's eval suites")
    return await harness.evaluate(body.file)
