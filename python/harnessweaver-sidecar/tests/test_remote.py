"""A Python app's ``where: sidecar`` guard, answered by harnessd itself (DESIGNS No. 24).

The app's harness and the sidecar run in this process; the request between them
goes through httpx's ASGI transport instead of a socket, so nothing calls out (R14).
"""

import json
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

import harnessweaver as hw
from harnessweaver.modules.guardrails import remote
from harnessweaver.spec import load_spec
from harnessweaver.testing import ScriptedModel, harness_for_test, scripted

pytestmark = pytest.mark.anyio

APP_SPEC = {
    "apiVersion": "harnessweaver/v1",
    "kind": "Harness",
    "metadata": {"name": "app-next-to-harnessd"},
    "models": {"provider": "scripted", "replies": [{"text": "ok"}]},
    "sidecar": {"url": "http://harnessd.test"},
    "guardrails": {"input": [{"id": "pii", "use": "pii.regex", "where": "sidecar"}]},
    "tasks": {"echo": {"runner": "direct"}},
}


@pytest.fixture
def through_harnessd(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """Send the app's remote checks to ``app`` (harnessd) in-process."""

    async def send(
        url: str, body: bytes, headers: Mapping[str, str], seconds: float
    ) -> tuple[int, bytes]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            response = await client.post(url, content=body, headers=dict(headers))
        return response.status_code, response.content

    monkeypatch.setattr(remote, "send_http", send)


def app_harness(tmp_path: Path) -> tuple[hw.Harness, ScriptedModel]:
    (tmp_path / "harness.yaml").write_text(json.dumps(APP_SPEC), encoding="utf-8")
    model = scripted("ok")
    return harness_for_test(load_spec(tmp_path / "harness.yaml"), model=model), model


@pytest.mark.usefixtures("through_harnessd")
async def test_the_sidecar_redacts_before_the_model_sees_anything(
    app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESSD_TOKEN", app.state.token)
    harness, model = app_harness(tmp_path)
    result = await harness.run("echo", "mail ann@example.com")
    assert result.ok, result.error
    assert model.requests[0].messages[-1].content == "mail [EMAIL]"


@pytest.mark.usefixtures("through_harnessd")
async def test_a_wrong_token_blocks_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESSD_TOKEN", "sk-test-wrong")
    harness, model = app_harness(tmp_path)
    result = await harness.run("echo", "mail ann@example.com")
    assert result.status is hw.RunStatus.BLOCKED  # the guard fails closed (R2)
    assert model.requests == []
