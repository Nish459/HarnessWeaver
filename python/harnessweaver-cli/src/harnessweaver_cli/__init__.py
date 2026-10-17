"""Developer tooling for HarnessWeaver: the ``harnessweaver`` command."""

from importlib.metadata import version as _version

__version__: str = _version("harnessweaver-cli")

__all__ = ["__version__"]
