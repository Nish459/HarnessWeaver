"""``harnessweaver gateway litellm|mcp``: what a gateway may let through (ADR-0039)."""

import json
from pathlib import Path
from typing import Any

import yaml
from typer.testing import CliRunner

from harnessweaver.spec import load_spec
from harnessweaver_cli.gateway import gateway_tools, litellm_config, upstream_env
from harnessweaver_cli.main import app

runner = CliRunner()

SPEC: dict[str, Any] = {
    "apiVersion": "harnessweaver/v1",
    "kind": "Harness",
    "metadata": {"name": "desk"},
    "models": {
        "provider": "openai.chat",
        "default": "small",
        "aliases": {"fast": "fast-chat", "strong": "strong-chat"},
        "allowed_aliases": ["fast", "small"],
    },
    "tools": {"manifests": ["tools/*.tool.yaml"], "approval_by_risk": {"high": "required"}},
    "observability": {
        "exporter": "otlp",
        "endpoint": "http://collector:4318",
        "configure_sdk": True,
    },
    "tasks": {
        "help": {
            "runner": "direct",
            "budget": {"deadline": "90s"},
            "approvals": {"tools": ["close_ticket"]},
        }
    },
}

TOOLS: dict[str, dict[str, Any]] = {
    "search_docs": {
        "input_schema": {
            "type": "object",
            "properties": {
                "space": {"type": "string", "enum": ["help", "ops.team"]},
                "query": {"type": "string"},
                "ticket": {"type": "string", "pattern": "^T-[0-9]+$"},
            },
        }
    },
    "mcp_search": {"transport": "mcp", "server": "mcp://search.example", "scopes": ["search:read"]},
    "refund": {"approval": {"when": "args.amount_usd > 100"}},
    "wire_money": {"risk": "high"},
    "close_ticket": {},
    "send_mail": {"egress": ["mail.example.com"]},
    "globex_only": {"tenants": ["globex"]},
    "busy": {"rate_limit": {"per_principal": "10/m"}},
    "retired": {"enabled": False},
    "swapped": {"definition_digest": "sha256:" + "0" * 64},
}


def project(tmp_path: Path, **sections: Any) -> Path:
    (tmp_path / "tools").mkdir()
    for name, fields in TOOLS.items():
        body = {"handler": "desk:run"} if fields.get("transport") != "mcp" else {}
        manifest = {
            "apiVersion": "harnessweaver/v1",
            "kind": "Tool",
            "metadata": {"name": name},
            "spec": {**body, "description": f"The {name} tool.", **fields},
        }
        (tmp_path / "tools" / f"{name}.tool.yaml").write_text(json.dumps(manifest), "utf-8")
    spec = tmp_path / "harness.yaml"
    spec.write_text(json.dumps({**SPEC, **sections}), encoding="utf-8")
    return spec


def test_only_tools_whose_manifest_needs_no_run_are_allowed(tmp_path: Path) -> None:
    tools = gateway_tools(load_spec(project(tmp_path)))
    assert [t.tool for t in tools.tools] == ["mcp_search", "search_docs"]
    mcp = tools.tools[0]
    assert (mcp.server, mcp.scopes, mcp.digest[:7]) == (
        "mcp://search.example",
        ("search:read",),
        "sha256:",
    )
    reasons = {w.tool: w.reason for w in tools.withheld}
    assert reasons == {
        "busy": "its rate limits are counted by the harness",
        "close_ticket": "it can need a person's approval, which only the harness can wait for",
        "globex_only": "it is enabled for some tenants only",
        "refund": "it can need a person's approval, which only the harness can wait for",
        "retired": "it is disabled",
        "send_mail": "it has egress, and the trifecta check needs what the run has seen (S3)",
        "swapped": "its pinned digest doesn't match its definition (S2)",
        "wire_money": "it can need a person's approval, which only the harness can wait for",
    }


def test_the_litellm_config_follows_the_spec(tmp_path: Path) -> None:
    effective = load_spec(project(tmp_path))
    config = litellm_config(effective, gateway_tools(effective))
    assert [m["model_name"] for m in config["model_list"]] == ["fast-chat", "small"]
    assert (
        config["model_list"][0]["litellm_params"]["model"]
        == f"os.environ/{upstream_env('fast-chat')}"
    )
    assert config["router_settings"] == {
        "num_retries": 2,
        "model_group_alias": {"fast": "fast-chat"},  # strong isn't an allowed alias
        "timeout": 90,
    }
    assert config["litellm_settings"] == {"turn_off_message_logging": True, "callbacks": ["otel"]}
    assert config["environment_variables"]["OTEL_ENDPOINT"] == "http://collector:4318"
    guard = config["guardrails"][0]["litellm_params"]
    assert (guard["default_action"], guard["default_on"]) == ("deny", True)
    rules = {rule["id"]: rule for rule in guard["rules"]}
    assert rules["allow-search_docs"]["allowed_param_patterns"] == {
        "space": r"^(?:help|ops\.team)$",
        "ticket": "^T-[0-9]+$",
    }
    assert rules["withhold-refund"]["decision"] == "deny"


def test_content_capture_and_no_deadline_change_the_settings(tmp_path: Path) -> None:
    spec = project(
        tmp_path,
        observability={"capture_content": True},
        tasks={"help": {"runner": "direct"}},
        models={"provider": "scripted", "replies": [{"text": "ok"}]},
    )
    effective = load_spec(spec)
    config = litellm_config(effective, gateway_tools(effective))
    assert config["litellm_settings"] == {"turn_off_message_logging": False}
    assert config["router_settings"] == {"num_retries": 2}
    assert config["model_list"] == []
    assert "environment_variables" not in config


def test_the_commands_print_or_write_yaml(tmp_path: Path) -> None:
    spec = project(tmp_path)
    printed = runner.invoke(app, ["gateway", "litellm", str(spec)])
    assert printed.exit_code == 0, printed.output
    assert "#   refund: it can need a person's approval" in printed.output
    assert yaml.safe_load(printed.output)["general_settings"] == {
        "master_key": "os.environ/LITELLM_MASTER_KEY"
    }
    out = tmp_path / "gateway" / "tools.yaml"
    written = runner.invoke(app, ["gateway", "mcp", str(spec), "-o", str(out)])
    assert written.exit_code == 0, written.output
    document = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert (document["kind"], document["default"]) == ("ToolAllowList", "deny")


def test_a_spec_that_doesnt_load_fails(tmp_path: Path) -> None:
    (tmp_path / "harness.yaml").write_text("kind: Harness\n", encoding="utf-8")
    result = runner.invoke(app, ["gateway", "mcp", str(tmp_path / "harness.yaml")])
    assert result.exit_code == 1
    assert "error:" in result.output
