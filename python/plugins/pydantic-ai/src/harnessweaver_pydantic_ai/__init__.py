"""HarnessWeaver plugin for Pydantic AI.

Contributes a pydantic_ai.agent runner and an adapter that governs an existing
Pydantic AI agent through harness.wrap(agent).
"""

from importlib.metadata import version as _version

__version__: str = _version("harnessweaver-pydantic-ai")

__all__ = ["__version__"]
