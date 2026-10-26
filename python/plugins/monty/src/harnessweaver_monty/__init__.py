"""HarnessWeaver plugin for the Monty sandbox.

Contributes ``monty.sandbox``, which runs code-executing tools (``transport:
code``) in pydantic-monty worker processes, never in the host process (S4).
Importing it imports nothing from pydantic-monty (S8).
"""

from importlib.metadata import version as _version

import harnessweaver as hw
from harnessweaver_monty.sandbox import MontySandbox

__version__: str = _version("harnessweaver-monty")

plugin = hw.Plugin(
    namespace="monty",
    version=__version__,
    providers=[MontySandbox],
    description="A sandbox for code-executing tools (monty.sandbox).",
)

__all__ = ["MontySandbox", "__version__", "plugin"]
