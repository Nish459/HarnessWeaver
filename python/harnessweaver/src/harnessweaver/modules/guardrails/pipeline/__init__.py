"""The guardrails pipeline: the spec's guards become middleware on hook points (DESIGNS No. 20).

| Stage         | Hook point      | Content checked                          |
| ------------- | --------------- | ---------------------------------------- |
| `input`       | `input.before`  | every string in the input                |
| `context`     | `context.after` | each retrieved item; `block` drops it    |
| `tool_result` | `tool.after`    | every string in the tool's output        |
| `output`      | `output.before` | every string in the candidate output     |
| `stream`      | `stream.chunk`  | each streamed chunk                      |

Semantics (fixtures suite ``guards``):

* Guards run in list order, baseline items first. Each guard is one middleware,
  so redactions chain and the most severe answer wins (No. 8).
* A provider proposes an action; the spec's ``action`` overrides it whenever the
  provider flags something. Asking to redact what a provider can't redact blocks.
* ``mode: log_only`` (or ``action: log_only``) records what the guard would have
  done and lets the content through (R8).
* Consecutive ``parallel: true`` guards in one band run concurrently as a group.
  Their redactions are then applied in list order, each guard re-checking the
  content the previous one redacted.
* The band comes from the layer that declared the guard: org profiles ->
  ``baseline``, built-in profiles -> ``platform``, the app -> ``app``, a task's
  own guards -> ``task``.
"""

from harnessweaver.modules.guardrails.pipeline.guards import (
    LAYER_BANDS,
    STAGE_HOOKS,
    Guard,
    Verdict,
    check,
)
from harnessweaver.modules.guardrails.pipeline.handlers import guard_handler
from harnessweaver.modules.guardrails.pipeline.install import install_guardrails

__all__ = [
    "LAYER_BANDS",
    "STAGE_HOOKS",
    "Guard",
    "Verdict",
    "check",
    "guard_handler",
    "install_guardrails",
]
