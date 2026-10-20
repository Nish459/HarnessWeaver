"""__dist__: a HarnessWeaver plugin under the namespace ``__ns__``.

Installing it registers nothing and imports nothing: HarnessWeaver finds it
through the ``harnessweaver.plugins`` entry point and imports it only when a
spec names one of its contributions, such as ``use: __ns__.banned_words``
(DESIGNS No. 13, RULES S8). So this module must not do I/O when it is imported.
"""

import harnessweaver as hw
from __ns___harness.guards import BannedWords, BannedWordsConfig

plugin = hw.Plugin(
    namespace="__ns__",
    version="0.1.0",
    contract=">=1.0,<2",
    providers=[BannedWords],
    description="Guards for __ns__ apps.",
)

__all__ = ["BannedWords", "BannedWordsConfig", "plugin"]
