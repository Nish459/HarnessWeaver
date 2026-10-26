"""monty.sandbox: code-executing tools run away from the host (S4)."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

import harnessweaver as hw
from harnessweaver.core.plugins import provider_info
from harnessweaver.core.registry import PluginCatalog, PluginSource
from harnessweaver.testing import harness_for_test, scripted, text, tool_call
from harnessweaver_monty import MontySandbox

pytestmark = pytest.mark.anyio

LIMITS = hw.SandboxLimits(timeout=timedelta(seconds=2), max_memory_mb=32)


async def test_code_returns_its_last_value_and_prints() -> None:
    ran = await MontySandbox().run(
        "print('hi')\nsum(x * 2 for x in data)", {"data": [1, 2, 3]}, LIMITS
    )
    assert ran == hw.SandboxResult(value=12, stdout="hi\n")


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("open('/etc/hosts').read()", "PermissionError"),
        ("import os\nos.environ['HOME']", "not supported"),
        ("import socket", "ModuleNotFoundError"),
        ("while True:\n    pass", "TimeoutError"),
        ("x = [0] * (10 ** 9)", "MemoryError"),
        ("def f(:", "SyntaxError"),
        ("1 / 0", "ZeroDivisionError"),
    ],
)
async def test_code_cant_reach_the_host_or_run_away(code: str, error: str) -> None:
    ran = await MontySandbox().run(
        code, {}, hw.SandboxLimits(timeout=timedelta(seconds=1), max_memory_mb=32)
    )
    assert ran.error is not None
    assert error in ran.error
    assert ran.value is None


async def test_values_json_cant_hold_are_described() -> None:
    ran = await MontySandbox().run("{1, 2}", {}, LIMITS)
    assert ran.error is None
    assert ran.value == [1, 2]


def test_the_sandbox_takes_no_settings() -> None:
    # Harnesses build sandboxes with no settings, so there is nothing to configure.
    with pytest.raises(hw.errors.SpecError, match="takes no settings"):
        provider_info(MontySandbox).build({"grace": "5s"})


async def test_a_code_tool_in_a_harness(tmp_path: Path) -> None:
    (tmp_path / "tools").mkdir()
    manifest = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Tool",
        "metadata": {"name": "python"},
        "spec": {
            "transport": "code",
            "sandbox": "monty",
            "description": "Run Python on the given numbers.",
            "input_schema": {
                "type": "object",
                "properties": {"code": {"type": "string"}, "numbers": {"type": "array"}},
                "required": ["code"],
            },
            "limits": {"timeout": "2s", "max_memory_mb": 32},
        },
    }
    (tmp_path / "tools" / "python.tool.yaml").write_text(json.dumps(manifest), encoding="ascii")
    document = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Harness",
        "metadata": {"name": "calc"},
        "tools": {"manifests": ["tools/*.tool.yaml"]},
        "tasks": {"calc": {"runner": "direct", "tools": ["python"]}},
    }
    path = tmp_path / "harness.yaml"
    path.write_text(json.dumps(document), encoding="ascii")
    model = scripted(tool_call("python", code="max(numbers)", numbers=[3, 9, 4]), text("9"))
    catalog = PluginCatalog([PluginSource("monty", "harnessweaver_monty:plugin", "entry_point")])
    harness = harness_for_test(path, model=model, catalog=catalog)
    result = await harness.run("calc", "what is the largest?")
    assert result.ok, result.error
    assert model.requests[-1].messages[-1].content == '{"value": 9, "stdout": ""}'
