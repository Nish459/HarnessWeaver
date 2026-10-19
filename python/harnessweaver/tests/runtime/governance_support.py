"""Helpers for the governance tests: tool manifests on disk and specs that use them."""

import json
from pathlib import Path
from typing import Any

import harnessweaver as hw

from .conftest import scripted, spec

AMOUNT = {
    "type": "object",
    "properties": {"amount_usd": {"type": "number", "minimum": 0}},
    "required": ["amount_usd"],
}
FINANCE = hw.Principal(id="bob", roles=("finance",))


def manifest(directory: Path, name: str, **fields: Any) -> Path:
    """Write ``tools/<name>.tool.yaml`` under ``directory``."""
    (directory / "tools").mkdir(exist_ok=True)
    document = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Tool",
        "metadata": {"name": name, "version": "1.0.0", "owner": "payments"},
        "spec": fields,
    }
    path = directory / "tools" / f"{name}.tool.yaml"
    path.write_text(json.dumps(document), encoding="ascii")
    return path


def refund_tool(directory: Path, **fields: Any) -> Path:
    return manifest(
        directory,
        "refund_payment",
        handler="hw_testkit:refund_payment",
        description="Refund a payment.",
        input_schema=AMOUNT,
        side_effect="write_external",
        risk="high",
        **fields,
    )


def call(name: str, **arguments: Any) -> dict[str, Any]:
    return {"tool_calls": [{"id": f"call_{name}", "name": name, "arguments": arguments}]}


def tool_spec(
    *replies: dict[str, Any], tools: list[str], after_tool: bool = True, **sections: Any
) -> dict[str, Any]:
    """A spec whose task ``t`` runs the direct runner over ``tools`` from manifest files.

    With ``after_tool``, the model says "done" after any tool result; without it,
    ``replies`` are used in order.
    """
    models = scripted(*replies, after_tool={"text": "done"}) if after_tool else scripted(*replies)
    document = spec(
        models=models,
        tools={"manifests": ["tools/*.tool.yaml"], **sections.pop("tools_section", {})},
        tasks={"t": {"runner": "direct", "tools": tools, **sections.pop("task", {})}},
    )
    document.update(sections)
    return document


def governor_notes(result: hw.RunResult) -> list[tuple[str | None, str | None]]:
    return [(e.code, e.reason) for e in result.trace if e.source == "harness.governor"]
