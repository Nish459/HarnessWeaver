"""Building a harness's governance from its spec: policy, tools, governor, approvals.

Everything here is checked when the harness loads (R4): the policy engine
compiles its rules, manifests and their handlers load, and every name resolves
through the plugin registry.
"""

from pathlib import Path

from harnessweaver.core.errors import SpecError
from harnessweaver.core.manifests import ToolManifest
from harnessweaver.core.ports import ApprovalChannel, PolicyEngine, Sandbox, ToolBackend
from harnessweaver.core.registry import Registry
from harnessweaver.modules.tools import ChainedTools, Governor, ManifestTools, load_manifests
from harnessweaver.modules.tools.manifests import approval_rules
from harnessweaver.spec.models import HarnessSpec

__all__ = ["build_channel", "build_governor", "build_policy", "build_tools"]


def build_policy(spec: HarnessSpec, registry: Registry) -> PolicyEngine:
    """The engine ``policy.use`` names, built from the spec's rules (ADR-0025).

    Raises:
        SpecError: For an unknown engine or a rule it can't compile.
    """
    policy = spec.policy
    settings = {
        "rules": [rule.model_dump(mode="json") for rule in policy.rules],
        "default_effect": policy.default_effect.value,
        **policy.provider_settings(),
    }
    return registry.provider("PolicyEngine", policy.use).build(settings)


def build_tools(
    spec: HarnessSpec, registry: Registry, base: Path, tools: ToolBackend | None
) -> tuple[ToolBackend | None, list[ToolManifest]]:
    """The tools from ``tools.manifests``, then any given in code, and the manifests read.

    Raises:
        SpecError: For a manifest that doesn't load, or a task that asks about an
            unknown tool.
    """
    manifests = load_manifests(spec.tools.manifests, base) if spec.tools.manifests else []
    backends: list[ToolBackend] = []
    if manifests:

        def sandbox(name: str) -> Sandbox:
            # "monty" is short for the plugin's "monty.sandbox".
            full = name if "." in name else f"{name}.sandbox"
            return registry.provider("Sandbox", full).build({})

        backends.append(ManifestTools(manifests, sandbox=sandbox))
    if tools is not None:
        backends.append(tools)
    backend = backends[0] if len(backends) == 1 else ChainedTools(backends) if backends else None
    for name, task in spec.tasks.items():
        for tool in task.approvals.tools if task.approvals else ():
            if backend is None or backend.describe(tool) is None:
                raise SpecError(f"tasks.{name}.approvals.tools: no tool named {tool!r}", task=name)
    return backend, manifests


def build_governor(
    spec: HarnessSpec, registry: Registry, policy: PolicyEngine, manifests: list[ToolManifest]
) -> Governor:
    """The governor every tool call passes (DESIGNS No. 17)."""
    judge = None
    if spec.tools.judge is not None:
        judge = registry.provider("Guardrail", spec.tools.judge.use).build(
            spec.tools.judge.provider_settings()
        )
    return Governor(
        policy=policy,
        tools=spec.tools,
        approval_rules=approval_rules(manifests),
        task_approvals={
            name: frozenset(task.approvals.tools)
            for name, task in spec.tasks.items()
            if task.approvals is not None and task.approvals.tools
        },
        judge=judge,
    )


def build_channel(spec: HarnessSpec, registry: Registry) -> ApprovalChannel:
    """The channel ``approvals.use`` names, with the section's extra keys as its settings."""
    return registry.provider("ApprovalChannel", spec.approvals.use).build(
        spec.approvals.provider_settings()
    )
