"""``harnessweaver gateway litellm|mcp``: gateway configs from the same spec (ADR-0039).

An app that calls models and tools straight through a gateway, with no SDK,
still gets the spec's model aliases and its tool allow-list. A gateway can't see
a run, though: what it has read, who approves, which tenant it is for. So a tool
is let through only when its manifest asks for nothing that needs the run
(approvals, egress and the trifecta, tenants, rate limits); the others are
withheld and run only through the harness (in process, or harnessd). Policy
rules, budgets and guards stay with the harness too.
"""

import math
import re
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from harnessweaver.core.errors import HarnessError
from harnessweaver.core.gateway import AllowedTool, GatewayMetadata, ToolAllowList, WithheldTool
from harnessweaver.core.manifests import ToolManifest, definition_digest
from harnessweaver.modules.tools import load_manifests
from harnessweaver.spec import EffectiveSpec, load_spec
from harnessweaver.spec.models import HarnessSpec
from harnessweaver_cli._load import fail, spec_path
from harnessweaver_cli.spec import Env, Path_, ProfileDirs

__all__ = [
    "gateway_app",
    "gateway_tools",
    "litellm_config",
    "render_allow_list",
    "render_litellm",
    "upstream_env",
]

gateway_app = typer.Typer(
    help="Gateway configs from the spec: LiteLLM Proxy, and a tool allow-list for MCP gateways.",
    no_args_is_help=True,
)

Out = Annotated[
    Path | None, typer.Option("--out", "-o", help="Write to this file instead of printing.")
]

RETRIES = 2
"""LiteLLM's retries: the gateway owns them, and SDK clients have theirs off (R5)."""


def upstream_env(model: str) -> str:
    """The variable that names the provider model behind a gateway model name, such as
    ``HARNESSWEAVER_UPSTREAM_FAST_CHAT`` for ``fast-chat``. The spec names only the
    gateway's models; which provider serves each is the gateway owner's choice."""
    return "HARNESSWEAVER_UPSTREAM_" + re.sub(r"[^A-Za-z0-9]", "_", model).upper()


def _withheld(manifest: ToolManifest, spec: HarnessSpec, approved: set[str]) -> str | None:
    """Why only the harness may run this tool, or ``None`` when a gateway may.

    Each reason is a manifest control that needs the run, so a gateway that
    allowed the tool would skip it.
    """
    body = manifest.spec
    if not body.enabled:
        return "it is disabled"
    digest = definition_digest(manifest.name, body.description, body.input_schema)
    if body.definition_digest is not None and body.definition_digest != digest:
        return "its pinned digest doesn't match its definition (S2)"
    if (
        body.approval is not None
        or spec.tools.approval_by_risk.get(body.risk) == "required"
        or manifest.name in approved
    ):
        return "it can need a person's approval, which only the harness can wait for"
    if body.egress:
        return "it has egress, and the trifecta check needs what the run has seen (S3)"
    if body.tenants:
        return "it is enabled for some tenants only"
    if body.rate_limit is not None:
        return "its rate limits are counted by the harness"
    return None


def _manifests(effective: EffectiveSpec) -> list[ToolManifest]:
    base = effective.path.parent if effective.path is not None else Path.cwd()
    found = load_manifests(effective.spec.tools.manifests, base)
    return sorted(found, key=lambda manifest: manifest.name)


def gateway_tools(effective: EffectiveSpec) -> ToolAllowList:
    """The tools a gateway may let through, and the ones it must withhold (ADR-0039).

    Raises:
        SpecError: For a manifest that doesn't load.
    """
    spec = effective.spec
    approved = {
        tool for task in spec.tasks.values() if task.approvals for tool in task.approvals.tools
    }
    allowed: list[AllowedTool] = []
    withheld: list[WithheldTool] = []
    for manifest in _manifests(effective):
        reason = _withheld(manifest, spec, approved)
        if reason is not None:
            withheld.append(WithheldTool(tool=manifest.name, reason=reason))
            continue
        body = manifest.spec
        allowed.append(
            AllowedTool(
                tool=manifest.name,
                transport=body.transport,
                server=body.server,
                # An unpinned manifest is pinned to what it says now; doctor warns about it.
                digest=body.definition_digest
                or definition_digest(manifest.name, body.description, body.input_schema),
                scopes=body.scopes,
            )
        )
    return ToolAllowList(
        metadata=GatewayMetadata(name=spec.metadata.name),
        tools=tuple(allowed),
        withheld=tuple(withheld),
    )


def _param_patterns(manifest: ToolManifest) -> dict[str, str]:
    """Regexes for the top-level string arguments the schema constrains: its ``pattern``,
    or its ``enum`` as alternatives. Other constraints stay with the governor (step 2)."""
    properties = manifest.spec.input_schema.get("properties")
    patterns: dict[str, str] = {}
    if not isinstance(properties, dict):
        return patterns
    for name, schema in sorted(properties.items()):
        if not isinstance(schema, dict):
            continue
        pattern, enum = schema.get("pattern"), schema.get("enum")
        if isinstance(pattern, str):
            patterns[name] = pattern
        elif isinstance(enum, list) and enum and all(isinstance(v, str) for v in enum):
            patterns[name] = "^(?:" + "|".join(re.escape(str(v)) for v in enum) + ")$"
    return patterns


def _timeout(effective: EffectiveSpec) -> int | None:
    """The longest deadline a run can have, in whole seconds: the gateway shouldn't keep
    a request going after the harness has given up on it."""
    spec = effective.spec
    deadlines = [spec.budgets.per_run.deadline] + [
        effective.run_budget(task).deadline for task in spec.tasks
    ]
    found = [deadline.total_seconds() for deadline in deadlines if deadline is not None]
    return math.ceil(max(found)) if found else None


def litellm_config(effective: EffectiveSpec, tools: ToolAllowList) -> dict[str, Any]:
    """A LiteLLM Proxy config: the gateway's models, the spec's aliases, retries and a
    timeout, content kept out of its logs, and a tool-permission guardrail on every
    request that allows only the allow-list's tools."""
    spec = effective.spec
    models = spec.models
    allowed_aliases = models.allowed_aliases
    aliases = {
        alias: target
        for alias, target in sorted(models.aliases.items())
        if allowed_aliases is None or alias in allowed_aliases
    }
    names = set(aliases.values())
    if models.default is not None:
        names.add(models.aliases.get(models.default, models.default))
    router: dict[str, Any] = {"num_retries": RETRIES}
    if aliases:
        router["model_group_alias"] = aliases
    timeout = _timeout(effective)
    if timeout is not None:
        router["timeout"] = timeout
    observability = spec.observability
    settings: dict[str, Any] = {"turn_off_message_logging": not observability.capture_content}
    config: dict[str, Any] = {
        "model_list": [
            {"model_name": name, "litellm_params": {"model": f"os.environ/{upstream_env(name)}"}}
            for name in sorted(names)
        ],
        "router_settings": router,
        "litellm_settings": settings,
    }
    if observability.exporter == "otlp":
        settings["callbacks"] = ["otel"]
        config["environment_variables"] = {
            "OTEL_EXPORTER": "otlp_http",
            "OTEL_ENDPOINT": observability.endpoint or "http://localhost:4318",
        }
    manifests = {manifest.name: manifest for manifest in _manifests(effective)}
    rules: list[dict[str, Any]] = []
    for tool in tools.tools:
        rule: dict[str, Any] = {
            "id": f"allow-{tool.tool}",
            "tool_name": f"^{re.escape(tool.tool)}$",
            "decision": "allow",
        }
        patterns = _param_patterns(manifests[tool.tool])
        if patterns:
            rule["allowed_param_patterns"] = patterns
        rules.append(rule)
    rules += [
        {"id": f"withhold-{w.tool}", "tool_name": f"^{re.escape(w.tool)}$", "decision": "deny"}
        for w in tools.withheld
    ]
    config["guardrails"] = [
        {
            "guardrail_name": "harnessweaver-tools",
            "litellm_params": {
                "guardrail": "tool_permission",
                "mode": "post_call",
                "default_on": True,
                "rules": rules,
                "default_action": "deny",  # no tool runs without a manifest (S2)
                "on_disallowed_action": "block",
            },
        }
    ]
    config["general_settings"] = {"master_key": "os.environ/LITELLM_MASTER_KEY"}
    return config


def _dump(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, width=100)


def _withheld_lines(tools: ToolAllowList) -> list[str]:
    if not tools.withheld:
        return []
    lines = ["Tools only the harness runs (denied here; run them through harnessd):"]
    return lines + [f"  {w.tool}: {w.reason}" for w in tools.withheld]


def _comment(lines: list[str]) -> str:
    return "".join(f"# {line}".rstrip() + "\n" for line in lines)


def render_litellm(effective: EffectiveSpec) -> str:
    """The LiteLLM Proxy config as YAML, with a header saying what to set and what is
    withheld."""
    tools = gateway_tools(effective)
    names = [entry["model_name"] for entry in litellm_config(effective, tools)["model_list"]]
    header = [
        f"LiteLLM Proxy config for {effective.spec.metadata.name}, generated by",
        "`harnessweaver gateway litellm` from the spec and its tool manifests (ADR-0039).",
        "Regenerate it when they change. In the gateway's environment (S1), set",
        "LITELLM_MASTER_KEY, the provider keys, and the provider model behind each name:",
        *[f"  {upstream_env(name)}" for name in names],
        "Policy rules, budgets, guards and approvals stay with the harness.",
        *_withheld_lines(tools),
    ]
    return _comment(header) + _dump(litellm_config(effective, tools))


def render_allow_list(effective: EffectiveSpec) -> str:
    """The neutral tool allow-list as YAML (schema ``tool-allow-list``)."""
    tools = gateway_tools(effective)
    header = [
        f"Tool allow-list for {effective.spec.metadata.name}, generated by",
        "`harnessweaver gateway mcp` (ADR-0039; schema tool-allow-list). An MCP gateway",
        "allows these tools only, pins each digest, and requires its scopes.",
    ]
    return _comment(header) + _dump(tools.model_dump(mode="json", by_alias=True))


def _emit(text: str, out: Path | None) -> None:
    if out is None:
        typer.echo(text, nl=False)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {out}")


@gateway_app.command("litellm")
def litellm(
    path: Path_ = None, env: Env = None, profile_dir: ProfileDirs = None, out: Out = None
) -> None:
    """A LiteLLM Proxy config: model aliases, router settings and tool permissions."""
    try:
        effective = load_spec(spec_path(path), env=env, profile_dirs=profile_dir or [])
        text = render_litellm(effective)
    except HarnessError as exc:
        raise fail(exc) from None
    _emit(text, out)


@gateway_app.command("mcp")
def mcp(
    path: Path_ = None, env: Env = None, profile_dir: ProfileDirs = None, out: Out = None
) -> None:
    """A neutral tool allow-list for an MCP gateway: tool, server, digest and scopes."""
    try:
        effective = load_spec(spec_path(path), env=env, profile_dirs=profile_dir or [])
        text = render_allow_list(effective)
    except HarnessError as exc:
        raise fail(exc) from None
    _emit(text, out)
