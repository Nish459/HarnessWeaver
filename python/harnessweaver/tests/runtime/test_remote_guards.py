"""Guards declared ``where: sidecar``: the provider's check runs in harnessd (ADR-0038)."""

import json
from collections.abc import Mapping
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.errors import PluginNotAllowed, SpecError
from harnessweaver.modules.guardrails import remote
from harnessweaver.spec.models import SidecarSpec

from .conftest import Builder, scripted, spec

pytestmark = pytest.mark.anyio

SIDECAR = {"url": "http://127.0.0.1:7070/", "token_env": "TEST_HARNESSD_TOKEN"}
REMOTE_PII = {"id": "pii", "use": "presidio.pii", "where": "sidecar", "entities": ["EMAIL"]}


class FakeSidecar:
    """Answers remote checks like harnessd would, and keeps what it was sent."""

    def __init__(self, status: int = 200, reply: Mapping[str, Any] | None = None) -> None:
        self.status = status
        self.reply = reply or {"action": "redact", "content": "mail [EMAIL]"}
        self.sent: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def __call__(
        self, url: str, body: bytes, headers: Mapping[str, str], seconds: float
    ) -> tuple[int, bytes]:
        self.sent.append((url, json.loads(body), dict(headers)))
        return self.status, json.dumps(self.reply).encode()


def remote_spec(guard: dict[str, Any] | None = None, **sections: Any) -> dict[str, Any]:
    return spec(
        models=scripted({"text": "ok"}),
        sidecar=SIDECAR,
        guardrails={"input": [guard or REMOTE_PII]},
        **sections,
    )


async def guard_input(harness: hw.Harness, text: str) -> hw.RunResult:
    session = harness.session(principal="alice")
    try:
        async with session as s:
            s.run_context.output = await s.guard("input", text)
    except hw.errors.HarnessError:
        pass  # the session's result records it
    assert session.result is not None
    return session.result


async def test_the_sidecar_runs_the_provider_and_the_guard_applies_its_answer(
    build: Builder, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidecar = FakeSidecar()
    monkeypatch.setattr(remote, "send_http", sidecar)
    monkeypatch.setenv("TEST_HARNESSD_TOKEN", "sk-test-sidecar")
    result = await guard_input(build(remote_spec()), "mail ann@example.com")
    assert result.ok, result.error
    assert result.output == "mail [EMAIL]"
    ((url, body, headers),) = sidecar.sent
    assert url == "http://127.0.0.1:7070/v1/guards/providers/presidio.pii:check"
    assert headers["Authorization"] == "Bearer sk-test-sidecar"
    assert body["content"] == "mail ann@example.com"
    assert body["settings"] == {"entities": ["EMAIL"]}
    assert body["stage"] == "input"
    assert body["envelope"]["principal"]["id"] == "alice"


def remote_guard() -> remote.RemoteGuardrail:
    sidecar = SidecarSpec.model_validate(SIDECAR)
    return remote.RemoteGuardrail(sidecar, "presidio.pii", {}, "input")


@pytest.mark.parametrize(
    ("status", "reply", "token", "why"),
    [
        (200, None, None, "set TEST_HARNESSD_TOKEN"),
        (
            401,
            {"code": "policy_denied", "type": "Unauthorized", "message": "a token is needed"},
            "t",
            r"HTTP 401 \(Unauthorized: a token is needed\)",
        ),
        (502, {"oops": True}, "t", "HTTP 502$"),
        (200, {"verdict": "fine"}, "t", "isn't a GuardResult"),
    ],
)
async def test_a_failing_sidecar_raises_a_provider_error(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    reply: dict[str, Any] | None,
    token: str | None,
    why: str,
) -> None:
    monkeypatch.setattr(remote, "send_http", FakeSidecar(status, reply))
    if token is not None:
        monkeypatch.setenv("TEST_HARNESSD_TOKEN", token)
    env = hw.Envelope.new(tenant="default", principal="alice")
    with pytest.raises(hw.errors.ProviderError, match=why):
        await remote_guard().check("mail ann@example.com", env)


async def test_test_mode_never_calls_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_HARNESSD_TOKEN", "sk-test-sidecar")
    env = hw.Envelope.new(tenant="default", principal="alice")
    with pytest.raises(hw.errors.ProviderError, match="test mode"):
        await remote_guard().check("hello", env)


@pytest.mark.parametrize(("fail_mode", "status"), [("closed", "blocked"), ("open", "completed")])
async def test_an_unreachable_sidecar_follows_the_guards_fail_mode(
    build: Builder, monkeypatch: pytest.MonkeyPatch, fail_mode: str, status: str
) -> None:
    monkeypatch.setenv("TEST_HARNESSD_TOKEN", "sk-test-sidecar")
    harness = build(remote_spec({**REMOTE_PII, "fail_mode": fail_mode}))
    result = await guard_input(harness, "hello")  # test mode: the default sender refuses
    assert result.status.value == status
    (failed,) = [e for e in result.trace if e.kind is hw.TraceKind.FAILURE]
    assert failed.details["error_type"] == "ProviderError"


def test_a_remote_guard_needs_a_sidecar_url_and_an_allowed_namespace(build: Builder) -> None:
    no_url = spec(models=scripted({"text": "ok"}), guardrails={"input": [REMOTE_PII]})
    with pytest.raises(SpecError, match=r"needs sidecar\.url"):
        build(no_url)
    with pytest.raises(PluginNotAllowed, match="presidio"):
        build(remote_spec(plugins={"local": ["hw_testkit"], "allow": ["testkit"]}))
