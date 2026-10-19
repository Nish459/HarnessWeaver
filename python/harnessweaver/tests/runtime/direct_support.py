"""Helpers shared by the direct-runner tests."""

from typing import Any

import harnessweaver as hw
from harnessweaver.core.trace import TraceKind

__all__ = ["SUMMARY", "hooks_fired", "script", "task"]

SUMMARY = "hw_testkit:Summary"


def task(**fields: Any) -> dict[str, Any]:
    return {"runner": "direct", **fields}


def hooks_fired(result: hw.RunResult) -> list[str]:
    return [e.hook.value for e in result.trace if e.kind is TraceKind.HOOK and e.hook]


def script(*rules: dict[str, Any]) -> dict[str, Any]:
    return {"use": "testkit.script", "rules": list(rules)}
