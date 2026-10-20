"""``harnessweaver add guard``, ``add tool`` and ``tools pin`` on a rendered project."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import harnessweaver as hw
from harnessweaver.spec.yaml import load_yaml_file
from harnessweaver_cli.main import app

runner = CliRunner()

TOOLS = '''"""The project's tools."""


def lookup_order(order_id: str, include_lines: bool = False, idempotency_key: str = "") -> dict:
    """Look up an order by its id.

    Args:
        order_id: The order's id, such as A-1001.
        include_lines (bool): Whether to include the order's lines,
            which makes the answer longer.
    """
    return {"order": order_id}


def undocumented(x: int) -> int:
    return x


def splat(*args: int) -> int:
    """Takes anything."""
    return 0
'''


def spec_text(project: Path) -> str:
    return (project / "harness.yaml").read_text(encoding="utf-8")


def test_add_guard_adds_a_shadow_guard_and_keeps_comments(project: Path) -> None:
    before = spec_text(project)
    result = runner.invoke(
        app, ["add", "guard", "regex.deny", "--stage", "output", "--set", "patterns=[refund]"]
    )
    assert result.exit_code == 0, result.output
    assert "added guardrails.output[regex-deny] (regex.deny) in shadow mode" in result.output
    after = spec_text(project)
    assert after.startswith(before.splitlines()[0])  # the header comment survived
    assert "- {id: regex-deny, use: regex.deny, mode: log_only, patterns: [refund]}" in after
    spec = hw.load(project / "harness.yaml").spec.spec
    (guard,) = [g for g in spec.guardrails.output if g.use == "regex.deny"]
    assert (guard.use, guard.mode) == ("regex.deny", "log_only")  # R8


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["nope.guard"], "nope"),  # the edit doesn't load
        (["pii.regex", "--set", "oops"], "must look like KEY=VALUE"),
        (["regex.deny", "--set", "patterns=[ok]", "--action", "explode"], "regex-deny].action"),
    ],
)
def test_a_guard_that_doesnt_load_leaves_the_spec_alone(
    project: Path, args: list[str], message: str
) -> None:
    before = spec_text(project)
    result = runner.invoke(app, ["add", "guard", *args])
    assert result.exit_code == 1
    assert message in result.output
    assert spec_text(project) == before


def test_a_guard_id_is_used_once(project: Path) -> None:
    assert runner.invoke(app, ["add", "guard", "pii.regex", "--id", "pii"]).exit_code == 0
    again = runner.invoke(app, ["add", "guard", "pii.regex", "--id", "pii"])
    assert again.exit_code == 1
    assert "already has a guard 'pii'" in again.output


def test_add_tool_writes_a_manifest_from_the_function(project: Path) -> None:
    (project / "app" / "tools.py").write_text(TOOLS, encoding="utf-8")
    result = runner.invoke(app, ["add", "tool", "app.tools:lookup_order", "--risk", "medium"])
    assert result.exit_code == 0, result.output
    assert "added tools/*.tool.yaml to tools.manifests" in result.output
    manifest = hw.ToolManifest.model_validate(_manifest(project))
    assert manifest.spec.handler == "app.tools:lookup_order"
    assert manifest.spec.description == "Look up an order by its id."
    assert manifest.spec.risk is hw.Risk.MEDIUM
    schema = manifest.spec.input_schema
    assert schema["required"] == ["order_id"]
    assert schema["properties"] == {
        "order_id": {"type": "string", "description": "The order's id, such as A-1001."},
        "include_lines": {
            "type": "boolean",
            "default": False,
            "description": "Whether to include the order's lines, which makes the answer longer.",
        },
    }  # idempotency_key is the governor's to fill in
    validated = runner.invoke(app, ["spec", "validate"])
    assert validated.exit_code == 0, validated.output


def _manifest(project: Path) -> object:
    return load_yaml_file(project / "tools" / "lookup_order.tool.yaml")


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        ("app.tools:undocumented", "has no docstring"),
        ("app.tools:splat", "*args and **kwargs"),
        ("app.tools:missing", "can't import"),
        ("nocolon", "isn't 'package.module:function'"),
    ],
)
def test_add_tool_refuses_what_it_cant_describe(project: Path, handler: str, message: str) -> None:
    (project / "app" / "tools.py").write_text(TOOLS, encoding="utf-8")
    result = runner.invoke(app, ["add", "tool", handler])
    assert result.exit_code == 1
    assert message in result.output


def test_tools_pin_pins_and_re_pins(project: Path) -> None:
    (project / "app" / "tools.py").write_text(TOOLS, encoding="utf-8")
    assert runner.invoke(app, ["add", "tool", "app.tools:lookup_order"]).exit_code == 0
    refused = runner.invoke(app, ["add", "tool", "app.tools:lookup_order"])
    assert refused.exit_code == 1
    assert "--force" in refused.output
    first = runner.invoke(app, ["tools", "pin"])
    assert first.exit_code == 0, first.output
    assert "pinned  lookup_order: sha256:" in first.output
    file = project / "tools" / "lookup_order.tool.yaml"
    assert file.read_text(encoding="utf-8").startswith("# lookup_order: written by")
    assert "ok      lookup_order is pinned" in runner.invoke(app, ["tools", "pin"]).output
    changed = file.read_text(encoding="utf-8").replace("Look up an order", "Find an order")
    file.write_text(changed, encoding="utf-8")
    assert "re-pinned lookup_order" in runner.invoke(app, ["tools", "pin"]).output
    doctor = runner.invoke(app, ["doctor"])
    assert "all pinned" in doctor.output
    unknown = runner.invoke(app, ["tools", "pin", "--tool", "nope"])
    assert unknown.exit_code == 1
    assert "no manifest for nope" in unknown.output


def test_tools_pin_needs_manifests(project: Path) -> None:
    result = runner.invoke(app, ["tools", "pin"])
    assert result.exit_code == 1
    assert "no tools.manifests" in result.output
