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
