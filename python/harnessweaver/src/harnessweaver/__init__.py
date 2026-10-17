"""HarnessWeaver: the composable AI harness framework.

Weave your own AI harness. Bring your models, choose your plugins, define
your execution.
"""

from importlib.metadata import version as _version

__version__: str = _version("harnessweaver")

__all__ = ["__version__"]
