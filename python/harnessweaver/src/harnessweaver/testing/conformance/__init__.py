"""The conformance checks every plugin contribution must pass (RULES T5).

``pytest --harnessweaver-conformance=<namespace>`` runs them as tests (see
``harnessweaver.testing.conformance_suite``). They are plain async functions
that raise ``AssertionError``, so they also run outside pytest.

| Check | Applies to |
| --- | --- |
| The plugin's metadata, names, contract range, profiles and templates | the plugin |
| Importing the plugin does no I/O and changes no global state (S8) | the plugin |
| Builds from its config (or its ``sample`` settings) | every contribution |
| Results validate against the contract | guardrails, deciders, model providers, state stores |
| Fresh instances repeat their results | deterministic providers |
| A guard that times out blocks when it fails closed | guardrails |
| No raw content reaches logs, spans or traces (R9) | guardrails, model providers |
| p95 latency within the declared ``latency_class`` | guards, deciders, offline models, stores |
| Answers every declared hook with an outcome | middleware |
| A task runs, firing only hooks the runner declares (R4) | runners |
| A call fires the declared hooks, in lifecycle order (R4) | adapters (needs ``sample``) |

Live model providers must refuse the network in test mode (R14).
"""

from harnessweaver.testing.conformance.builds import check_builds
from harnessweaver.testing.conformance.common import LATENCY_LIMITS, LIFECYCLE, Subject
from harnessweaver.testing.conformance.hooks import check_adapter, check_middleware, check_runner
from harnessweaver.testing.conformance.observability import check_latency, check_no_raw_content
from harnessweaver.testing.conformance.plugin_checks import (
    check_import_is_inert,
    check_plugin,
    load_plugin,
)
from harnessweaver.testing.conformance.results import (
    check_deterministic,
    check_results,
    check_timeout_blocks,
)
from harnessweaver.testing.conformance.suite import CHECKS, applies, subjects

__all__ = [
    "CHECKS",
    "LATENCY_LIMITS",
    "LIFECYCLE",
    "Subject",
    "applies",
    "check_adapter",
    "check_builds",
    "check_deterministic",
    "check_import_is_inert",
    "check_latency",
    "check_middleware",
    "check_no_raw_content",
    "check_plugin",
    "check_results",
    "check_runner",
    "check_timeout_blocks",
    "load_plugin",
    "subjects",
]
