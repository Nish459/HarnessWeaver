"""RunContext: the mutable state of one run, and the governed operations runners use.

Runners, sessions and adapters never call a model, a tool or a guard directly.
They call the methods here, which fire the hook points around each operation,
apply budgets and deadlines, and turn halting outcomes into
:class:`~harnessweaver.errors.RunInterrupted` errors (ADR-0020). That is how one
set of controls covers every integration style (DESIGNS No. 7, No. 15).

The envelope stays immutable: when labels or the budget change, the context
produces a new one (DESIGNS No. 10).
"""

from harnessweaver.core.context.access import (
    MODEL_RETRIES,
    SUSPENDABLE_HOOKS,
    ModelAccess,
    NoTools,
    PendingApproval,
    PromptSource,
    TaskInfo,
)
from harnessweaver.core.context.run import RunContext, current_run

__all__ = [
    "MODEL_RETRIES",
    "SUSPENDABLE_HOOKS",
    "ModelAccess",
    "NoTools",
    "PendingApproval",
    "PromptSource",
    "RunContext",
    "TaskInfo",
    "current_run",
]
