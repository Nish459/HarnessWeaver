"""HarnessWeaver plugin for CEL policies.

Contributes ``cel.policy``, a policy engine that evaluates ``policy.rules`` in
full CEL through cel-python. Importing it imports nothing from cel-python (S8).
"""

from importlib.metadata import version as _version

import harnessweaver as hw
from harnessweaver_cel.policy import CelPolicy

__version__: str = _version("harnessweaver-cel")

plugin = hw.Plugin(
    namespace="cel",
    version=__version__,
    providers=[CelPolicy],
    description="Policy rules in full CEL (cel.policy).",
)

__all__ = ["CelPolicy", "__version__", "plugin"]
