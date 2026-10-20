"""The ``tools`` module: manifests, the registry and the nine-step governor (DESIGNS No. 17).

No tool runs without a manifest (S2): ``tools.manifests`` names ``kind: Tool``
files, each with a transport (``native``, ``http`` or ``code`` in a sandbox), a
pinned definition digest and its governance. Every call passes the governor.
"""

from harnessweaver.modules.tools.governor import Governor
from harnessweaver.modules.tools.limits import RateLimiter
from harnessweaver.modules.tools.manifests import (
    approval_rules,
    load_manifest,
    load_manifests,
    manifest_files,
)
from harnessweaver.modules.tools.registry import ChainedTools, ManifestTools
from harnessweaver.modules.tools.sanitize import REMOVED, sanitize
from harnessweaver.modules.tools.transports import HttpSender, send_http

__all__ = [
    "REMOVED",
    "ChainedTools",
    "Governor",
    "HttpSender",
    "ManifestTools",
    "RateLimiter",
    "approval_rules",
    "load_manifest",
    "load_manifests",
    "manifest_files",
    "sanitize",
    "send_http",
]
