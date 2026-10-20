"""Loading tool manifests, and the http and code transports (S2, S4, R4, R14)."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.errors import ProviderError, SpecError
from harnessweaver.modules.tools import registry as registry_module
from harnessweaver.modules.tools import send_http

from .conftest import Builder
from .governance_support import AMOUNT, call, manifest, refund_tool, tool_spec

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (
            {"handler": "hw_testkit:refund_payment", "input_schema": {"patternProperties": {}}},
            "isn't supported",
        ),
        (
            {"handler": "hw_testkit:refund_payment", "approval": {"when": "args.amount_usd >"}},
            "approval.when",
        ),
        ({"description": "no handler"}, "needs a handler"),
        ({"handler": "hw_testkit:nope"}, "can't import"),
        ({"transport": "mcp", "server": "mcp://payments.example"}, "isn't supported yet"),
        ({"transport": "mcp"}, "names its server"),
        ({"handler": "hw_testkit:refund_payment", "server": "mcp://x"}, "only an mcp tool"),
        ({"transport": "code"}, "must name a sandbox"),
        ({"handler": "hw_testkit:refund_payment", "sandbox": "monty"}, "only code tools"),
        (
            {
                "handler": "hw_testkit:refund_payment",
                "rate_limit": {"per_principal": "ten a minute"},
            },
            "10/m",
        ),
    ],
)
async def test_bad_manifests_fail_to_load(
    build: Builder, tmp_path: Path, testkit: Any, fields: dict[str, Any], message: str
) -> None:
    manifest(tmp_path, "refund_payment", **fields)
    with pytest.raises(SpecError, match=message):
        build(tool_spec({"text": "x"}, tools=["refund_payment"]), tools=None)


async def test_manifest_files_must_exist_be_tools_and_be_unique(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    with pytest.raises(SpecError, match="no file matches"):
        build(tool_spec({"text": "x"}, tools=[]), tools=None)
    refund_tool(tmp_path)
    (tmp_path / "tools" / "copy.tool.yaml").write_text(
        (tmp_path / "tools" / "refund_payment.tool.yaml").read_text(), encoding="ascii"
    )
    with pytest.raises(SpecError, match="also defined in"):
        build(tool_spec({"text": "x"}, tools=["refund_payment"]), tools=None)
    (tmp_path / "tools" / "copy.tool.yaml").write_text(
        json.dumps({"kind": "Harness"}), encoding="ascii"
    )
    with pytest.raises(SpecError, match="isn't a 'kind: Tool' manifest"):
        build(tool_spec({"text": "x"}, tools=["refund_payment"]), tools=None)


async def test_an_input_schema_can_live_in_its_own_file(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    (tmp_path / "tools" / "schemas").mkdir(parents=True)
    (tmp_path / "tools" / "schemas" / "amount.json").write_text(
        json.dumps(AMOUNT), encoding="ascii"
    )
    manifest(
        tmp_path,
        "refund_payment",
        handler="hw_testkit:refund_payment",
        input_schema={"$ref": "schemas/amount.json"},
    )
    harness = build(
        tool_spec(call("refund_payment", amount_usd=-1), tools=["refund_payment"]), tools=None
    )
    result = await harness.run("t", "refund")
    assert result.error is not None
    assert result.error.details["code"] == "schema_invalid"
    manifest(
        tmp_path,
        "refund_payment",
        handler="hw_testkit:refund_payment",
        input_schema={"$ref": "gone.json"},
    )
    with pytest.raises(SpecError, match=r"no file 'gone\.json'"):
        build(tool_spec({"text": "x"}, tools=["refund_payment"]), tools=None)


async def test_manifest_tools_and_tools_in_code_work_together(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    refund_tool(tmp_path)
    replies = (call("refund_payment", amount_usd=5), call("lookup"), {"text": "done"})
    harness = build(tool_spec(*replies, tools=["refund_payment", "lookup"], after_tool=False))
    result = await harness.run("t", "go")
    assert result.ok, result.error
    assert [name for name, _ in testkit.RECORDER.handled] == ["refund_payment"]
    assert [c.name for c in testkit.RECORDER.tool_calls] == ["lookup"]


class _Server:
    def __init__(self, status: int = 200, body: bytes = b'{"refund_id": "rf_1"}') -> None:
        self.status, self.body = status, body
        self.sent: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def __call__(
        self, url: str, body: bytes, headers: Mapping[str, str], seconds: float
    ) -> tuple[int, bytes]:
        self.sent.append((url, json.loads(body), dict(headers)))
        return self.status, self.body


def _http_tool(tmp_path: Path, **fields: Any) -> None:
    manifest(
        tmp_path,
        "refund_payment",
        transport="http",
        url="https://payments.example.com/refunds",
        input_schema=AMOUNT,
        **fields,
    )


async def test_an_http_tool_posts_its_arguments(
    build: Builder, tmp_path: Path, testkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = _Server()
    monkeypatch.setattr(registry_module, "send_http", server)
    monkeypatch.setenv("PAYMENTS_TOKEN", "sk-test-not-real")
    _http_tool(tmp_path, headers_env={"Authorization": "PAYMENTS_TOKEN"})
    harness = build(
        tool_spec(call("refund_payment", amount_usd=5), tools=["refund_payment"]), tools=None
    )
    result = await harness.run("t", "refund")
    assert result.ok, result.error
    ((url, body, headers),) = server.sent
    assert (url, body) == ("https://payments.example.com/refunds", {"amount_usd": 5})
    assert headers["Authorization"] == "sk-test-not-real"
    assert headers["Idempotency-Key"].startswith(f"{result.run_id}:sha256:")
    assert '"rf_1"' in str(testkit.RECORDER.requests[-1].messages[-1].content)


@pytest.mark.parametrize(
    ("server", "env"),
    [(_Server(status=502), True), (_Server(body=b"<html>"), True), (_Server(), False)],
)
async def test_http_failures_reach_the_model_as_tool_errors(
    build: Builder,
    tmp_path: Path,
    testkit: Any,
    monkeypatch: pytest.MonkeyPatch,
    server: _Server,
    env: bool,
) -> None:
    monkeypatch.setattr(registry_module, "send_http", server)
    if env:
        monkeypatch.setenv("PAYMENTS_TOKEN", "sk-test-not-real")
    else:
        monkeypatch.delenv("PAYMENTS_TOKEN", raising=False)
    _http_tool(tmp_path, headers_env={"Authorization": "PAYMENTS_TOKEN"})
    harness = build(
        tool_spec(call("refund_payment", amount_usd=5), tools=["refund_payment"]), tools=None
    )
    result = await harness.run("t", "refund")
    assert result.ok
    assert "ToolError" in str(testkit.RECORDER.requests[-1].messages[-1].content)


async def test_the_default_sender_refuses_the_network_in_test_mode() -> None:
    with pytest.raises(ProviderError, match="test mode"):
        await send_http("https://payments.example.com", b"{}", {}, 1.0)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("sum(numbers)", '{"value": {"length": 12, "inputs": ["numbers"]}, "stdout": "ok"}'),
        ("raise ValueError", '{"error": "ValueError: told to", "stdout": "partial"}'),
    ],
)
async def test_a_code_tool_runs_in_its_sandbox(
    build: Builder, tmp_path: Path, testkit: Any, code: str, expected: str
) -> None:
    manifest(tmp_path, "python", transport="code", sandbox="testkit", limits={"timeout": "2s"})
    harness = build(
        tool_spec(call("python", code=code, numbers=[1, 2]), tools=["python"]), tools=None
    )
    result = await harness.run("t", "compute")
    assert result.ok
    assert testkit.RECORDER.requests[-1].messages[-1].content == expected


async def test_a_code_tool_needs_its_code(build: Builder, tmp_path: Path, testkit: Any) -> None:
    manifest(tmp_path, "python", transport="code", sandbox="testkit")
    harness = build(tool_spec(call("python", numbers=[1]), tools=["python"]), tools=None)
    result = await harness.run("t", "compute")
    assert "ToolError" in str(testkit.RECORDER.requests[-1].messages[-1].content)
    assert result.ok


def test_a_manifest_names_its_facts() -> None:
    document = {
        "metadata": {"name": "refund_payment", "version": "2.1.0"},
        "spec": {"handler": "app:refund", "risk": "high", "data_access": ["pii:customer"]},
    }
    tool = hw.ToolManifest.model_validate(document)
    assert tool.info() == hw.ToolInfo(
        name="refund_payment", version="2.1.0", risk=hw.Risk.HIGH, data_access=("pii:customer",)
    )
    assert tool.tool_spec().name == "refund_payment"
    assert tool.computed_digest() == hw.definition_digest("refund_payment", "", {"type": "object"})
