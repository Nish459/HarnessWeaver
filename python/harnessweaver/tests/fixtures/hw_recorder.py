"""What the test plugin saw: hooks, requests, tool calls, envelopes and handled calls."""

from dataclasses import dataclass, field
from typing import Any

import harnessweaver as hw

__all__ = ["RECORDER", "Recorder"]


@dataclass
class Recorder:
    hooks: list[str] = field(default_factory=list)
    requests: list[hw.ModelRequest] = field(default_factory=list)
    tool_calls: list[hw.ToolCall] = field(default_factory=list)
    envelopes: list[hw.Envelope] = field(default_factory=list)
    notes: list[Any] = field(default_factory=list)
    handled: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def reset(self) -> None:
        self.hooks.clear()
        self.requests.clear()
        self.tool_calls.clear()
        self.envelopes.clear()
        self.notes.clear()
        self.handled.clear()


RECORDER = Recorder()
