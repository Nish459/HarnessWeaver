"""HarnessWeaver plugin for CEL policies.

Contributes a cel.policy policy engine that evaluates full CEL through cel-
python.
"""

from importlib.metadata import version as _version

__version__: str = _version("harnessweaver-cel")

__all__ = ["__version__"]
