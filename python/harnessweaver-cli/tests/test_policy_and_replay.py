"""``harnessweaver policy test`` and ``replay`` on a small refunds project."""

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest
from typer.testing import CliRunner

import harnessweaver as hw
from harnessweaver_cli.main import app

runner = CliRunner()

HANDLERS = '''"""The refunds project's tools."""


def refund(amount_usd: float) -> dict[str, float]:
    return {"refunded": amount_usd}
'''

SPEC: dict[str, Any] = {
    "apiVersion": "harnessweaver/v1",
    "kind": "Harness",
    "metadata": {"name": "refunds"},
    "models": {
        "provider": "scripted",
        "replies": [
            {"tool_calls": [{"name": "refund_payment", "arguments": {"amount_usd": 5}}]},
            {"text": "done"},
        ],
    },
    "tools": {"manifests": ["tools/*.tool.yaml"]},
    "policy": {"rules": [{"id": "no-globex", "when": "tenant == 'globex'", "effect": "deny"}]},
    "state": {"use": "sqlite", "path": ".harness/state.db", "record": True},
    "tasks": {"refund": {"runner": "direct", "tools": ["refund_payment"]}},
}

MANIFEST = {
    "apiVersion": "harnessweaver/v1",
    "kind": "Tool",
    "metadata": {"name": "refund_payment", "version": "1.0.0", "owner": "payments"},
    "spec": {
        "handler": "handlers:refund",
        "description": "Refund a payment.",
        "input_schema": {
            "type": "object",
            "properties": {"amount_usd": {"type": "number", "minimum": 0}},
            "required": ["amount_usd"],
        },
        "side_effect": "write_external",
        "risk": "high",
        "approval": {"when": "args.amount_usd > 100", "approver_role": "finance"},
    },
}

CASES = {
    "cases": [
        {
            "id": "small",
            "tool": "refund_payment",
            "args": {"amount_usd": 5},
            "principal": "alice",
            "expect": "allow",
        },
        {
            "id": "big",
            "tool": "refund_payment",
            "args": {"amount_usd": 500},
            "expect": "require_approval",
            "approver_role": "finance",
        },
        {
            "id": "globex",
            "tool": "refund_payment",
            "args": {"amount_usd": 5},
            "tenant": "globex",
            "expect": "block",
            "code": "policy_denied",
        },
    ]
}


def write(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="ascii")  # JSON is YAML 1.2


@pytest.fixture
def refunds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "refunds"
    write(root / "harness.yaml", SPEC)
    write(root / "tools" / "refund_payment.tool.yaml", MANIFEST)
    write(root / "policy_tests.yaml", CASES)
    (root / "handlers.py").write_text(HANDLERS, encoding="ascii")
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "path", [str(root), *sys.path])  # as when the app runs there
    yield root
    sys.modules.pop("handlers", None)


def test_policy_tests_pass(refunds: Path) -> None:
    result = runner.invoke(app, ["policy", "test"])
    assert result.exit_code == 0, result.output
    assert "ok   small: allow at step 7" in result.output
    assert "ok   globex: block at step 3" in result.output
    assert "3 of 3 policy tests passed" in result.output


def test_a_wrong_expectation_fails(refunds: Path) -> None:
    cases = json.loads(json.dumps(CASES))
    cases["cases"][0]["expect"] = "block"
    cases["cases"][1]["approver_role"] = "support"
    write(refunds / "more.yaml", cases)
    result = runner.invoke(app, ["policy", "test", "--cases", "more.yaml"])
    assert result.exit_code == 1, result.output
    assert "FAIL small: decision 'allow', not 'block' (allowed)" in result.output
    assert "FAIL big: approver_role 'finance', not 'support'" in result.output
    shown = json.loads(
        runner.invoke(app, ["policy", "test", "-c", "more.yaml", "--format", "json"]).output
    )
    assert [(row["id"], row["ok"]) for row in shown] == [
        ("small", False),
        ("big", False),
        ("globex", True),
    ]


def test_policy_tests_that_cant_run_exit_2(refunds: Path) -> None:
    missing = runner.invoke(app, ["policy", "test", "--cases", "nope.yaml"])
    assert missing.exit_code == 2
    assert "no policy tests at nope.yaml" in missing.output
    write(refunds / "bad.yaml", {"cases": [{"id": "x", "tool": "refund_payment"}]})
    bad = runner.invoke(app, ["policy", "test", "--cases", "bad.yaml"])
    assert bad.exit_code == 2
    assert "cases.0.expect: Field required" in bad.output


def recorded_run(project: Path) -> str:
    async def run() -> str:
        harness = hw.load(project / "harness.yaml")
        try:
            result = await harness.run("refund", "refund order 7")
            assert result.ok, result.error
            return result.run_id
        finally:
            await harness.aclose()

    return anyio.run(run)


def test_replaying_a_recorded_run(refunds: Path) -> None:
    run_id = recorded_run(refunds)
    same = runner.invoke(app, ["replay", run_id])
    assert same.exit_code == 0, same.output
    assert f"same: run {run_id} (refund) ended completed; the replay ended completed" in same.output
    assert "model answers used: 2 of 2" in same.output
    spec = json.loads(json.dumps(SPEC))
    spec["policy"]["rules"].append({"id": "freeze", "when": "true", "effect": "deny"})
    write(refunds / "harness.yaml", spec)
    changed = runner.invoke(app, ["replay", run_id])
    assert changed.exit_code == 1, changed.output
    assert "the replay ended blocked" in changed.output
    assert "+ tool.before harness.governor policy_denied" in changed.output
    shown = json.loads(runner.invoke(app, ["replay", run_id, "--format", "json"]).output)
    assert (shown["differs"], shown["replayed"]["status"]) == (True, "blocked")


def test_runs_that_cant_be_replayed_exit_2(refunds: Path) -> None:
    result = runner.invoke(app, ["replay", "run_missing"])
    assert result.exit_code == 2
    assert "no run run_missing" in result.output
