import sys
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from typer.testing import CliRunner

import harnessweaver
import harnessweaver_cli
from harnessweaver_cli.main import app

runner = CliRunner()


def test_version_flag_reports_cli_and_core_versions() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"harnessweaver-cli {harnessweaver_cli.__version__}" in result.output
    assert f"harnessweaver {harnessweaver.__version__}" in result.output


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_sidecar_runs_harnessd_on_the_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    served: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **where: served.update(app=app, **where))
    monkeypatch.setenv("HARNESSD_TOKEN", "sk-test-harnessd")
    spec = tmp_path / "harness.yaml"
    spec.write_text(
        "apiVersion: harnessweaver/v1\nkind: Harness\nmetadata: { name: served }\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["sidecar", str(spec), "--port", "7171", "--max-body-bytes", "2048"]
    )
    assert result.exit_code == 0, result.output
    assert (served["host"], served["port"]) == ("127.0.0.1", 7171)
    assert served["app"].state.harness.name == "served"
    assert served["app"].state.max_body_bytes == 2048


def test_sidecar_says_how_to_install_harnessd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "harnessweaver_sidecar.main", None)  # import fails
    result = runner.invoke(app, ["sidecar"])
    assert result.exit_code == 1
    assert "uv add harnessweaver-sidecar" in result.output
