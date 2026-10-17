"""HarnessWeaver plugin for Anthropic models.

Contributes an anthropic.messages model provider for the Claude Messages API
and an adapter for harness.instrument(Anthropic client).
"""

from importlib.metadata import version as _version

__version__: str = _version("harnessweaver-anthropic")

__all__ = ["__version__"]
