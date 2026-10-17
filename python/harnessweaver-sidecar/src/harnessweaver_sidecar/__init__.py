"""harnessd: serves the HarnessWeaver core to every other language over HTTP."""

from importlib.metadata import version as _version

__version__: str = _version("harnessweaver-sidecar")

__all__ = ["__version__"]
