"""HarnessWeaver plugin for Monty sandbox.

Contributes a monty.sandbox executor that runs code-executing tools in the
pydantic-monty sandbox.
"""

from importlib.metadata import version as _version

__version__: str = _version("harnessweaver-monty")

__all__ = ["__version__"]
