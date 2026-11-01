"""Runner for the ``governor`` fixtures: digests, rates, schemas, policy, steps 1-7 and step 9."""

from dataclasses import dataclass, field
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.digests import canonical_json
from harnessweaver.core.jsonschema import SchemaError, check_schema, validate
from harnessweaver.core.manifests import OutputPolicy, parse_rate
from harnessweaver.core.ports import ToolDescription
from harnessweaver.core.trace import RunTrace
from harnessweaver.modules.policy import CelLitePolicy
from harnessweaver.modules.tools import Governor, sanitize
from harnessweaver.modules.tools.manifests import approval_rules
from harnessweaver.spec.models import ToolsSpec

pytestmark = [pytest.mark.conformance_suite("governor"), pytest.mark.anyio]


@dataclass
class _Run:
    """What the governor reads from a run (``GovernedRun``)."""

    envelope: hw.Envelope
    clock: hw.FakeClock
    fallback_approver_role: str | None = None
    trace: RunTrace = field(init=False)

    def __post_init__(self) -> None:
        self.trace = RunTrace(self.clock)


def _run(case: dict[str, Any]) -> _Run:
    clock = hw.FakeClock()
    principal = hw.Principal.model_validate(
        case.get("principal", {"id": "alice", "roles": ["support"]})
    )
    envelope = hw.Envelope.new(
        tenant=case.get("tenant", "acme"), principal=principal, task=case.get("task"), clock=clock
    )
    envelope = envelope.with_labels(hw.Labels.model_validate(case.get("labels", {})))
    return _Run(envelope, clock, case.get("fallback_role"))


def _tool(spec: dict[str, Any]) -> ToolDescription:
    spec = dict(spec)
    name = spec.pop("name")
    if spec.pop("manifest", True) is False:
        info = hw.ToolInfo.model_validate({"name": name, **spec})
        return ToolDescription(info, hw.ToolSpec(name=name))
    manifest = hw.ToolManifest.model_validate({"metadata": {"name": name}, "spec": spec})
    return ToolDescription.from_manifest(manifest)


async def _steps(case: dict[str, Any]) -> hw.ToolVerdict:
    tool = _tool(case["tool"])
    policy = CelLitePolicy(hw.PolicyConfig.model_validate(case.get("policy", {})))
    governor = Governor(
        policy=policy,
        tools=ToolsSpec.model_validate(case.get("tools", {})),
        approval_rules=approval_rules([tool.manifest] if tool.manifest else []),
        task_approvals={
            task: frozenset(tools) for task, tools in case.get("task_approvals", {}).items()
        },
    )
    run = _run(case)
    limit = tool.manifest.spec.rate_limit if tool.manifest else None
    for _ in range(case.get("previous_calls", 0)):
        assert limit is not None
        wanted = []
        if limit.per_principal:
            count, window = parse_rate(limit.per_principal)
            wanted.append(((tool.info.name, "principal", run.envelope.principal.id), count, window))
        if limit.per_tenant:
            count, window = parse_rate(limit.per_tenant)
            wanted.append(((tool.info.name, "tenant", run.envelope.tenant), count, window))
        assert governor.limiter.acquire(wanted, run.clock.now().timestamp()) is not None
    approval = None
    if case.get("approved"):
        approval = hw.ApprovalDecision(
            approval_id="apr_1",
            decision="approve",
            approver=hw.Principal(id="bob", roles=tuple(case.get("approved_roles", ()))),
        )
    call = hw.ToolCall(id="call_1", name=tool.info.name, arguments=case["args"])
    return await governor.authorize(run, call, tool, approval)


async def test_governor(case: dict[str, Any]) -> None:
    expect = case["expect"]
    if "definition" in case:
        definition = case["definition"]
        if "canonical" in expect:
            assert canonical_json(definition) == expect["canonical"]
        digest = hw.definition_digest(
            definition["name"], definition["description"], definition["input_schema"]
        )
        assert digest == expect["digest"]
    elif "rate" in case:
        if expect.get("error"):
            with pytest.raises(ValueError):
                parse_rate(case["rate"])
        else:
            assert parse_rate(case["rate"]) == (expect["count"], expect["seconds"])
    elif "schema" in case:
        if expect.get("error"):
            with pytest.raises(SchemaError):
                check_schema(case["schema"])
            return
        check_schema(case["schema"])
        problems = validate(case["value"], case["schema"])
        assert (not problems) == expect["valid"], problems
        if not expect["valid"]:
            assert sorted({p.split(": ", 1)[0] for p in problems}) == expect["locations"]
    elif "rules" in case:
        config = hw.PolicyConfig(rules=case["rules"], default_effect=case["default_effect"])
        decision = await CelLitePolicy(config).decide(
            hw.PolicyRequest.model_validate(case["request"])
        )
        assert (decision.effect.value, decision.rule) == (expect["effect"], expect["rule"])
    elif "tool" in case:
        verdict = await _steps(case)
        assert (verdict.decision, verdict.step, verdict.code) == (
            expect["decision"],
            expect["step"],
            expect["code"],
        ), verdict.reason
    else:
        result = hw.ToolResult(call_id="call_1", output=case["output"])
        policy = OutputPolicy.model_validate(case["policy"])
        limit = policy.max_bytes or case.get("max_output_bytes", 20_000)
        env = hw.Envelope.new(tenant="acme", principal="alice", clock=hw.FakeClock())
        cleaned, _ = await sanitize(result, policy, limit, env)
        assert (cleaned.output, cleaned.truncated, cleaned.untrusted) == (
            expect["output"],
            expect["truncated"],
            expect["untrusted"],
        )
