"""``harnessweaver plugin new`` and ``plugin list``."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harnessweaver_cli.main import app

runner = CliRunner()

SCAFFOLD = {
    "README.md",
    "pyproject.toml",
    "src/acme_tools_harness/__init__.py",
    "src/acme_tools_harness/guards.py",
    "src/acme_tools_harness/py.typed",
    "tests/test_guards.py",
}


def files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_plugin_new_scaffolds_a_package_that_passes_its_own_checks(tmp_path: Path) -> None:
    target = tmp_path / "acme-tools-harness"
    result = runner.invoke(app, ["plugin", "new", "acme_tools", str(target)])
    assert result.exit_code == 0, result.output
    assert files(target) == SCAFFOLD
    pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "acme-tools-harness"' in pyproject
    assert 'acme_tools = "acme_tools_harness:plugin"' in pyproject
    assert "__ns__" not in "".join((target / f).read_text(encoding="utf-8") for f in SCAFFOLD)
    # Its tests and the conformance suite, run where it was written (outside this repo):
    # the conformance suite takes the module, since nothing is installed here (T5).
    environment = {**os.environ, "PYTHONPATH": str(target / "src")}
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=--import-mode=importlib",
            "--harnessweaver-conformance=acme_tools_harness:plugin",
        ],
        cwd=target,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "passed" in done.stdout


@pytest.mark.parametrize(
    ("namespace", "message"),
    [("Acme", "invalid namespace"), ("pii", "reserved for the built-in plugin")],
)
def test_plugin_new_refuses_bad_namespaces(tmp_path: Path, namespace: str, message: str) -> None:
    result = runner.invoke(app, ["plugin", "new", namespace, str(tmp_path / "x")])
    assert result.exit_code == 1
    assert message in result.output


def test_plugin_new_never_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["plugin", "new", "acme"]).exit_code == 0
    assert (tmp_path / "acme-harness" / "pyproject.toml").is_file()
    again = runner.invoke(app, ["plugin", "new", "acme"])
    assert again.exit_code == 1
    assert "--force" in again.output


def test_plugin_list_shows_installed_plugins() -> None:
    shown = json.loads(runner.invoke(app, ["plugin", "list", "--format", "json"]).output)
    rows = {row["namespace"]: row for row in shown["plugins"]}
    assert rows["openai"]["distribution"] == "harnessweaver-openai"
    assert rows["openai"]["compatible"] is True
    assert rows["pydantic_ai"]["contract"] == ">=1.0,<2"
    text = runner.invoke(app, ["plugin", "list"])
    assert text.exit_code == 0
    assert "harnessweaver-anthropic" in text.output
    assert "harnessweaver contract 1.0.0" in text.output
