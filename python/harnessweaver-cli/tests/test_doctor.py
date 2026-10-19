"""``harnessweaver doctor``: level, hooks, retry owners, pins, shadow guards, content."""

import json
from pathlib import Path

from typer.testing import CliRunner

from harnessweaver_cli.doctor import diagnose
from harnessweaver_cli.main import app

runner = CliRunner()
ORG = Path(__file__).resolve().parents[3] / "examples" / "_org"


def edit(project: Path, old: str, new: str) -> None:
    spec = project / "harness.yaml"
    text = spec.read_text(encoding="utf-8")
    assert old in text
    spec.write_text(text.replace(old, new), encoding="utf-8")


def test_a_fresh_project_is_healthy(project: Path) -> None:
    result = runner.invoke(app, ["doctor", "--strict"])
    assert result.exit_code == 0, result.output
    assert "adoption level L1; risk tier 'internal' requires L0" in result.output
    assert "to reach L2: policy.rules has at least one rule" in result.output
    assert "task extract: runner direct reaches every hook it needs" in result.output


def test_warnings_fail_only_with_strict(project: Path) -> None:
    edit(project, "api_key_env: LITELLM_API_KEY", "api_key_env: LITELLM_API_KEY\n  max_retries: 2")
    edit(project, "validation:", "observability: { capture_content: true }\n\nvalidation:")
    edit(
        project,
        "validation:\n",
        "guardrails:\n  output:\n    - { id: tone, use: pii.regex, mode: log_only }\n\n"
        "validation:\n",
    )
    findings = {(f.severity, f.check) for f in diagnose(project / "harness.yaml", None, [])}
    assert {("warn", "retries"), ("warn", "content"), ("warn", "shadow guards")} <= findings
    assert runner.invoke(app, ["doctor"]).exit_code == 0
    strict = runner.invoke(app, ["doctor", "--strict"])
    assert strict.exit_code == 1
    assert "let the gateway own retries" in strict.output
    assert "guardrails.output[tone] is in shadow mode" in strict.output


def test_unpinned_org_profiles_are_flagged(project: Path) -> None:
    edit(
        project,
        'extends: ["profile://extraction"]',
        'extends: ["org://acme-baseline", "profile://extraction"]',
    )
    findings = diagnose(project / "harness.yaml", None, [ORG])
    assert any(f.check == "pins" and "org://acme-baseline@^1" in f.message for f in findings)
    pinned = project / "harness.yaml"
    pinned.write_text(
        pinned.read_text(encoding="utf-8").replace("org://acme-baseline", "org://acme-baseline@^1"),
        encoding="utf-8",
    )
    assert ("ok", "pins") in {(f.severity, f.check) for f in diagnose(pinned, None, [ORG])}


def test_a_spec_that_wont_load_fails(project: Path) -> None:
    edit(project, "runner: direct", "runner: nosuch")
    result = runner.invoke(app, ["doctor", "--format", "json"])
    assert result.exit_code == 1
    findings = json.loads(result.output)
    assert findings[-1]["severity"] == "fail"
    assert findings[-1]["check"] == "load"


def test_tool_manifests_should_be_pinned(project: Path) -> None:
    (project / "tools").mkdir()
    tool = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Tool",
        "metadata": {"name": "lookup"},
        "spec": {"handler": "builtins:len", "description": "Look something up."},
    }
    (project / "tools" / "lookup.tool.yaml").write_text(json.dumps(tool), encoding="utf-8")
    edit(project, "validation:", 'tools: { manifests: ["tools/*.tool.yaml"] }\n\nvalidation:')
    findings = diagnose(project / "harness.yaml", None, [])
    (unpinned,) = [f for f in findings if f.check == "tools"]
    assert unpinned.severity == "warn"
    digest = unpinned.message.split("definition_digest: ")[1].split(" ")[0]
    tool["spec"]["definition_digest"] = digest  # type: ignore[index]
    (project / "tools" / "lookup.tool.yaml").write_text(json.dumps(tool), encoding="utf-8")
    assert ("ok", "tools") in {
        (f.severity, f.check) for f in diagnose(project / "harness.yaml", None, [])
    }
    tool["spec"]["description"] = "Look something up, and more."  # type: ignore[index]
    (project / "tools" / "lookup.tool.yaml").write_text(json.dumps(tool), encoding="utf-8")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "lookup changed since it was pinned" in result.output
