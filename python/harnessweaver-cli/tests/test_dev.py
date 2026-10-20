"""``harnessweaver dev``: the local stack it writes, and ``--up`` (ADR-0039)."""

import base64
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from harnessweaver.spec import load_spec
from harnessweaver_cli.gateway import render_litellm
from harnessweaver_cli.main import app

runner = CliRunner()

SPEC = {
    "apiVersion": "harnessweaver/v1",
    "kind": "Harness",
    "metadata": {"name": "desk"},
    "models": {
        "provider": "openai.chat",
        "base_url": "http://localhost:4000",
        "api_key_env": "DESK_GATEWAY_KEY",
        "default": "fast",
        "aliases": {"fast": "fast-chat"},
    },
}


def project(tmp_path: Path) -> Path:
    spec = tmp_path / "app" / "harness.yaml"
    spec.parent.mkdir()
    spec.write_text(json.dumps(SPEC), encoding="utf-8")
    return spec


def secrets_of(directory: Path) -> dict[str, str]:
    lines = (directory / ".env").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def test_it_writes_a_stack_wired_to_the_spec(tmp_path: Path) -> None:
    spec = project(tmp_path)
    profiles = tmp_path / "org-profiles"
    profiles.mkdir()
    result = runner.invoke(app, ["dev", str(spec), "-e", "dev", "--profile-dir", str(profiles)])
    assert result.exit_code == 0, result.output
    directory = spec.parent / ".harness" / "dev"
    assert (directory / ".gitignore").read_text(encoding="utf-8") == "*\n"
    assert (directory / "litellm.yaml").read_text(encoding="utf-8") == render_litellm(
        load_spec(spec, env="dev", profile_dirs=[profiles])
    )
    text = (directory / "compose.yaml").read_text(encoding="utf-8")
    assert "__" not in text  # every marker is filled in
    compose: dict[str, Any] = yaml.safe_load(text)
    services = compose["services"]
    assert set(services) >= {"litellm", "otel-collector", "harnessd", "langfuse-web"}
    for name, service in services.items():
        if name != "harnessd":  # built from deploy/harnessd/Dockerfile
            assert "@sha256:" in service["image"], name  # S5
        for port in service.get("ports", []):
            assert port.startswith("127.0.0.1:"), (name, port)  # S6
    harnessd = services["harnessd"]
    assert harnessd["command"] == ["harness.yaml"]
    assert harnessd["environment"]["HARNESSWEAVER_ENV"] == "dev"
    assert harnessd["environment"]["HARNESSWEAVER_PROFILE_PATH"] == "/profiles/0"
    assert f"{profiles.resolve()}:/profiles/0:ro" in harnessd["volumes"]
    assert harnessd["network_mode"] == "service:litellm"  # the spec's localhost URLs work
    collector = yaml.safe_load((directory / "otel-collector.yaml").read_text(encoding="utf-8"))
    assert "otlp_http/langfuse" in collector["exporters"]


def test_the_secrets_are_generated_once_and_then_kept(tmp_path: Path) -> None:
    spec = project(tmp_path)
    assert runner.invoke(app, ["dev", str(spec)]).exit_code == 0
    directory = spec.parent / ".harness" / "dev"
    first = secrets_of(directory)
    assert first["HARNESSWEAVER_UPSTREAM_FAST_CHAT"] == ""  # the developer fills it in
    assert first["OPENAI_API_KEY"] == ""
    assert first["DESK_GATEWAY_KEY"] == first["LITELLM_MASTER_KEY"]  # the app's key variable
    pair = f"{first['LANGFUSE_PUBLIC_KEY']}:{first['LANGFUSE_SECRET_KEY']}"
    assert base64.b64decode(first["LANGFUSE_OTLP_AUTH"]).decode() == pair
    assert len(first["ENCRYPTION_KEY"]) == 64
    assert runner.invoke(app, ["dev", str(spec)]).exit_code == 0
    assert secrets_of(directory) == first


def test_up_starts_the_stack_with_docker_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = project(tmp_path)
    calls: list[tuple[list[str], Path]] = []

    def run(command: list[str], *, cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
        calls.append((command, cwd))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "run", run)
    result = runner.invoke(app, ["dev", str(spec), "--up"])
    assert result.exit_code == 0, result.output
    assert calls == [
        (["/usr/bin/docker", "compose", "up", "-d"], spec.resolve().parent / ".harness" / "dev")
    ]
    assert "Langfuse http://127.0.0.1:3000" in result.output


def test_up_needs_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = runner.invoke(app, ["dev", str(project(tmp_path)), "--up"])
    assert result.exit_code == 1
    assert "docker isn't installed" in result.output
