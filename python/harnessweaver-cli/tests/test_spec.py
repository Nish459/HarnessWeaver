"""``harnessweaver spec validate|explain|diff``, ``hooks`` and ``contracts export``."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harnessweaver_cli.main import app

runner = CliRunner()


def test_validate_reports_the_level_layers_and_tasks(project: Path) -> None:
    result = runner.invoke(app, ["spec", "validate", "--env", "offline"])
    assert result.exit_code == 0, result.output
    assert "ok: demo is valid" in result.output
    assert "adoption level L1 (required: L0)" in result.output
    assert "profile://extraction" in result.output
    assert "tasks: extract" in result.output


def test_validate_as_json(project: Path) -> None:
    result = runner.invoke(app, ["spec", "validate", "harness.yaml", "--format", "json"])
    body = json.loads(result.output)
    assert body["ok"] is True
    assert (body["level"], body["required"], body["tasks"]) == ("L1", "L0", ["extract"])


def test_validate_fails_with_the_load_error(project: Path) -> None:
    spec = project / "harness.yaml"
    spec.write_text(spec.read_text(encoding="utf-8") + "surprise: true\n", encoding="utf-8")
    result = runner.invoke(app, ["spec", "validate"])
    assert result.exit_code == 1
    assert result.output.startswith("error: ")
    assert "surprise" in result.output


def test_validate_needs_a_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["spec", "validate"])
    assert result.exit_code == 1
    assert "no spec at harness.yaml" in result.output


def test_explain_shows_where_values_come_from(project: Path) -> None:
    result = runner.invoke(app, ["spec", "explain", "--path", "validation"])
    assert result.exit_code == 0, result.output
    assert "validation.max_repairs" in result.output
    assert "profile://extraction" in result.output
    assert "models." not in result.output


def test_explain_as_json(project: Path) -> None:
    result = runner.invoke(
        app, ["spec", "explain", "--path", "models.provider", "--format", "json"]
    )
    rows = json.loads(result.output)
    assert rows == [
        {
            "path": "models.provider",
            "value": "openai.chat",
            "layer": "harness.yaml",
            "locked_by": None,
        }
    ]


def test_diff_compares_effective_specs(project: Path) -> None:
    before = project / "before.yaml"
    shutil.copy(project / "harness.yaml", before)
    spec = project / "harness.yaml"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace("max_usd: 0.05", "max_usd: 0.10"), encoding="utf-8"
    )
    result = runner.invoke(app, ["spec", "diff", str(before), "harness.yaml", "--exit-code"])
    assert result.exit_code == 1
    assert "tasks.extract.budget.max_usd" in result.output
    same = runner.invoke(app, ["spec", "diff", "harness.yaml", "harness.yaml", "--exit-code"])
    assert same.exit_code == 0, same.output


def git(*args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
    )


def test_diff_reads_a_spec_from_git(project: Path) -> None:
    git("init", "-q")
    git("add", "harness.yaml", "harness.offline.yaml")
    git("commit", "-q", "-m", "spec")
    spec = project / "harness.yaml"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace("max_model_calls: 3", "max_model_calls: 2"),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["spec", "diff", "git:HEAD:harness.yaml", "harness.yaml"])
    assert result.exit_code == 0, result.output
    assert "tasks.extract.budget.max_model_calls" in result.output
    offline = runner.invoke(
        app, ["spec", "diff", "git:HEAD:harness.yaml", "harness.yaml", "-e", "offline"]
    )
    assert "models.provider" not in offline.output  # both sides got the overlay


@pytest.mark.parametrize(
    ("source", "message"),
    [("git:HEAD", "must look like git:<ref>:<path>"), ("git:nope:harness.yaml", "from git")],
)
def test_diff_reports_bad_git_sources(project: Path, source: str, message: str) -> None:
    git("init", "-q")
    result = runner.invoke(app, ["spec", "diff", source, "harness.yaml"])
    assert result.exit_code == 1
    assert message in result.output


def test_hooks_lists_each_chain_in_order(project: Path) -> None:
    result = runner.invoke(app, ["hooks", "--env", "offline", "--task", "extract"])
    assert result.exit_code == 0, result.output
    assert "guardrails.input[extraction-pii]" in result.output
    assert "validation.rules[summary-length]" in result.output
    assert "(not reached)" not in result.output
    assert "outbound hooks run task -> baseline" in result.output
    assert all(ord(c) < 128 for c in result.output)  # ASCII borders (D5)


def test_contracts_export_writes_and_checks(tmp_path: Path) -> None:
    out = tmp_path / "schemas"
    written = runner.invoke(app, ["contracts", "export", str(out)])
    assert written.exit_code == 0, written.output
    assert (out / "harness.schema.json").is_file()
    assert runner.invoke(app, ["contracts", "export", str(out), "--check"]).exit_code == 0
    (out / "harness.schema.json").write_text("{}", encoding="utf-8")
    stale = runner.invoke(app, ["contracts", "export", str(out), "--check"])
    assert stale.exit_code == 1
    assert "harness.schema.json" in stale.output


def test_the_checked_in_schemas_are_current() -> None:
    root = Path(__file__).resolve().parents[3]
    result = runner.invoke(
        app, ["contracts", "export", str(root / "contracts" / "schemas"), "--check"]
    )
    assert result.exit_code == 0, result.output
