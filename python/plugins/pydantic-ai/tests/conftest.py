"""Shared setup: the test agents module (``pai_agents``) is importable, and reset per test."""

import sys
from pathlib import Path

import pytest

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)  # specs name pai_agents:<agent>, as an app names its own module


@pytest.fixture(autouse=True)
def fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    import pai_agents

    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")
    pai_agents.reset()
