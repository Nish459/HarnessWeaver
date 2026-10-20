"""Every harnessd route, against the help desk spec (ADR-0038)."""

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import harnessweaver
import harnessweaver_sidecar
from harnessweaver_sidecar.app import create_app, openapi_document
from harnessweaver_sidecar.main import load

DESK = Path(__file__).resolve().parent / "desk"
ALICE = {"principal": "alice", "tenant": "acme"}


def post(client: TestClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def protected_routes() -> list[tuple[str, str]]:
    paths = openapi_document()["paths"]
    return [
        (method.upper(), re.sub(r"\{[a-z_]+\}", "x", path))
        for path, operations in paths.items()
        for method in operations
        if path != "/v1/health"
    ]


def test_health_needs_no_token_and_reports_versions(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "harnessd": harnessweaver_sidecar.__version__,
        "harnessweaver": harnessweaver.__version__,
    }


@pytest.mark.parametrize(("method", "path"), protected_routes())
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer sk-test-wrong"}])
def test_every_other_route_needs_the_token(
    app: FastAPI, method: str, path: str, headers: dict[str, str]
) -> None:
    response = TestClient(app).request(method, path, json={}, headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["code"] == "policy_denied"


def test_harnessd_never_runs_without_a_token() -> None:
    with pytest.raises(ValueError, match="bearer token"):
        create_app(load(DESK / "harness.yaml"), token="")


def test_spec_and_hooks_describe_what_is_served(client: TestClient) -> None:
    info = client.get("/v1/spec").json()
    assert info["name"] == "help-desk"
    assert info["api_version"] == "harnessweaver/v1"
    assert info["tasks"] == ["refund", "triage"]
    assert info["spec"]["metadata"]["name"] == "help-desk"
    hooks = client.get("/v1/hooks", params={"task": "refund"}).json()
    assert [entry["name"] for entry in hooks["input.before"]] == ["guardrails.input[pii]"]
    assert hooks["input.before"][0]["fail_mode"] == "closed"


def test_input_guards_redact_and_run_start_rules_still_apply(client: TestClient) -> None:
    redacted = post(client, "/v1/guards/input", {**ALICE, "content": "mail ann@example.com"})
    assert redacted["status"] == "completed"
    assert redacted["output"] == "mail [EMAIL]"
    # Each check is a run of its own, kept like any other (GET /v1/runs/{id}).
    kept = client.get(f"/v1/runs/{redacted['run_id']}").json()
    assert kept["status"] == "completed"
    banned = post(client, "/v1/guards/input", {"tenant": "banned", "content": "hi"})
    assert banned["status"] == "blocked"
    assert banned["error"]["details"]["code"] == "policy_denied"


def test_output_guards_block_a_secret(client: TestClient) -> None:
    result = post(client, "/v1/guards/output", {**ALICE, "content": "key AKIAIOSFODNN7EXAMPLE"})
    assert result["status"] == "blocked"
    assert "AKIA" not in str(result)  # reasons and findings only (R9)


def test_context_checks_recheck_acls(client: TestClient) -> None:
    items = [
        {"id": "kb-refunds", "content": "Open to all.", "source": "kb", "acl": {}},
        {
            "id": "kb-globex",
            "content": "Globex only.",
            "source": "kb",
            "acl": {"tenants": ["globex"]},
        },
        {"id": "no-acl", "content": "Nobody said who may read this.", "source": "kb"},
    ]
    body = {**ALICE, "tenant": "initech", "source": "kb", "items": items}
    kept = post(client, "/v1/guards/context", body)
    assert [item["id"] for item in kept["output"]] == ["kb-refunds"]
    unnamed = post(client, "/v1/guards/context", {**ALICE, "items": items})
    assert unnamed["status"] == "failed"
    assert unnamed["error"]["code"] == "validation_failed"


def test_tool_results_go_through_sanitize_not_a_guard_stage(client: TestClient) -> None:
    response = client.post("/v1/guards/tool_result", json={})
    assert response.status_code == 422
    sanitized = post(
        client,
        "/v1/tools/refund_payment/sanitize",
        {**ALICE, "arguments": {"amount_usd": 20}, "output": {"note": "card of ann@example.com"}},
    )
    assert sanitized["status"] == "completed"
    assert sanitized["output"]["output"] == {"note": "card of [EMAIL]"}
    assert sanitized["output"]["untrusted"] is True
    unknown = post(client, "/v1/tools/wire_money/sanitize", {**ALICE, "output": 1})
    assert unknown["error"]["code"] == "not_found"


def test_decisions_route_with_the_spec_router(client: TestClient) -> None:
    billing = post(client, "/v1/decisions/topic", {**ALICE, "text": "I want a refund"})
    assert billing["output"]["choice"] == "billing"
    other = post(client, "/v1/decisions/topic", {**ALICE, "text": "Hello there"})
    assert (other["output"]["choice"], other["output"]["kind"]) == ("other", "default")


def test_policy_and_authorize_decide_without_running_anything(client: TestClient) -> None:
    request = {"hook": "run.start", "principal": {"id": "alice"}, "tenant": "banned"}
    decision = post(client, "/v1/policy/evaluate", request)
    assert (decision["effect"], decision["rule"]) == ("deny", "no-banned-tenants")
    verdicts = {
        amount: post(
            client, "/v1/tools/refund_payment/authorize", {**ALICE, "args": {"amount_usd": amount}}
        )
        for amount in (20, 250, 1500)
    }
    assert verdicts[20]["decision"] == "allow"
    assert (verdicts[250]["decision"], verdicts[250]["approver_role"]) == (
        "require_approval",
        "finance",
    )
    assert (verdicts[1500]["decision"], verdicts[1500]["step"]) == ("block", 3)
    unknown = post(client, "/v1/tools/wire_money/authorize", ALICE)
    assert unknown["code"] == "tool_unknown"
    import harnessd_desk.tools

    assert harnessd_desk.tools.REFUNDS == []


def test_validate_parses_into_the_task_output_type(client: TestClient) -> None:
    good = {"summary": "Card charged twice", "priority": "high"}
    accepted = post(client, "/v1/validate", {**ALICE, "task": "triage", "output": good})
    assert (accepted["status"], accepted["output"]) == ("completed", good)
    wrong = post(
        client,
        "/v1/validate",
        {**ALICE, "task": "triage", "output": {**good, "priority": "urgent"}},
    )
    assert wrong["status"] == "failed"
    assert wrong["error"]["code"] == "validation_failed"
    assert "priority" in wrong["error"]["message"]
    missing = client.post("/v1/validate", json={"task": "nope", "output": 1})
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")


def test_a_run_waits_for_finance_then_refunds_once(client: TestClient) -> None:
    import harnessd_desk.tools

    waiting = post(client, "/v1/runs", {**ALICE, "task": "refund", "input": "Refund 250 dollars"})
    assert waiting["status"] == "awaiting_approval"
    approval = waiting["approval"]
    path = f"/v1/runs/{waiting['run_id']}/approvals/{approval['approval_id']}"
    refused = client.post(path, json={"approver": "bob"})
    assert (refused.status_code, refused.json()["type"]) == (403, "PolicyDenied")
    done = post(client, path, {"approver": {"id": "fran", "roles": ["finance"]}})
    assert (done["status"], done["output"]) == ("completed", "Refunded.")
    assert harnessd_desk.tools.REFUNDS == [250]
    assert client.get(f"/v1/runs/{waiting['run_id']}").json()["status"] == "completed"
    unknown = client.get("/v1/runs/run_nope")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "not_found")


def test_evals_run_a_listed_suite_or_one_sent_inline(client: TestClient) -> None:
    listed = post(client, "/v1/evals/run", {"file": "evals/refunds.yaml"})
    assert listed["passed"] is True
    inline = {
        "suite": "inline",
        "task": "refund",
        "graders": [{"status": "completed"}],
        "cases": [{"id": "hello", "input": "Hello", "principal": "alice"}],
    }
    assert post(client, "/v1/evals/run", {"dataset": inline})["passed"] is True
    unlisted = client.post("/v1/evals/run", json={"file": "../harness.yaml"})
    assert unlisted.status_code == 404
    both = client.post("/v1/evals/run", json={"file": "x", "dataset": inline})
    assert both.status_code == 422


def test_a_provider_check_runs_one_guardrail(client: TestClient) -> None:
    envelope = {"run_id": "run_1", "tenant": "acme", "principal": {"id": "alice"}}
    body = {"content": "mail ann@example.com", "envelope": envelope, "stage": "input"}
    result = post(client, "/v1/guards/providers/pii.regex:check", body)
    assert (result["action"], result["content"]) == ("redact", "mail [EMAIL]")
    wrong_stage = client.post(
        "/v1/guards/providers/grounded.citations:check", json={**body, "stage": "input"}
    )
    assert (wrong_stage.status_code, wrong_stage.json()["code"]) == (400, "spec_invalid")
    unknown = client.post("/v1/guards/providers/nope.guard:check", json=body)
    assert unknown.status_code == 400


def test_invalid_requests_never_echo_their_content(client: TestClient) -> None:
    body = {"task": "refund", "input": "x", "note": "ann@example.com"}
    response = client.post("/v1/runs", json=body)
    assert response.status_code == 422
    error = response.json()
    assert (error["code"], error["type"]) == ("validation_failed", "ValidationFailed")
    assert "note" in error["message"]
    assert "ann@example.com" not in response.text  # R9
