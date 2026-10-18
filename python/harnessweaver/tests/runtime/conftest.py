"""Helpers for runtime tests: the ``hw_testkit`` plugin and harness builders."""

import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.registry import PluginCatalog
from harnessweaver.core.telemetry import Telemetry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

type Builder = Callable[..., hw.Harness]


@pytest.fixture
def testkit(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The test plugin module, importable as ``hw_testkit``, with a fresh recorder."""
    monkeypatch.syspath_prepend(str(FIXTURES))
    import hw_testkit

    hw_testkit.RECORDER.reset()
    return hw_testkit


def spec(**sections: Any) -> dict[str, Any]:
    """A harness.yaml document that uses the test plugin."""
    document: dict[str, Any] = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Harness",
        "metadata": {"name": "test-app"},
        "plugins": {"local": ["hw_testkit"]},
    }
    document.update(sections)
    return document


def scripted(*replies: dict[str, Any], **models: Any) -> dict[str, Any]:
    """A ``models`` section answered by the test plugin's scripted provider."""
    return {"provider": "testkit.scripted", "replies": list(replies), **models}


def write(directory: Path, document: dict[str, Any], name: str = "harness.yaml") -> Path:
    path = directory / name
    path.write_text(json.dumps(document), encoding="ascii")  # JSON is valid YAML 1.2
    return path


@pytest.fixture
def build(tmp_path: Path, testkit: ModuleType) -> Builder:
    """Build a harness from a spec dict, with prompts and the test tools."""

    def make(
        document: dict[str, Any],
        *,
        tools: Any = "fake",
        clock: hw.Clock | None = None,
        prompts: dict[str, str] | None = None,
        catalog: PluginCatalog | None = None,
        telemetry: Telemetry | None = None,
    ) -> hw.Harness:
        for name, text in (prompts or {"reply@1": "Route {route}. Customer: {customer}"}).items():
            (tmp_path / "prompts").mkdir(exist_ok=True)
            (tmp_path / "prompts" / f"{name}.md").write_text(text, encoding="ascii")
        return hw.Harness.load(
            write(tmp_path, document),
            clock=clock or hw.FakeClock(),
            tools=testkit.FakeTools() if tools == "fake" else tools,
            catalog=catalog or PluginCatalog(),
            telemetry=telemetry,
        )

    return make
