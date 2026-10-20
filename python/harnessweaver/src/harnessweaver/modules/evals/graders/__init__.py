"""The deterministic graders (DESIGNS No. 23, fixtures suite ``evals``).

Each is an ``Evaluator`` provider. A dataset gives a grader's settings as a map,
or as one value that fills the field its config names in ``SHORTHAND``:
``{field_equals: total}`` is ``{field_equals: {field: total}}``. Reasons name
fields, texts by position and rules, never the output's content (R9).
"""

from harnessweaver.modules.evals.graders.base import GraderConfig, NoSettings
from harnessweaver.modules.evals.graders.compare import Exact, FieldEquals, NumericClose
from harnessweaver.modules.evals.graders.outcome import (
    GuardFired,
    GuardFiredConfig,
    SchemaValid,
    Status,
    guard_matches,
)
from harnessweaver.modules.evals.graders.text import (
    CITATION_PATTERN,
    CitationPresent,
    Contains,
    Regex,
)

__all__ = [
    "CITATION_PATTERN",
    "CitationPresent",
    "Contains",
    "Exact",
    "FieldEquals",
    "GraderConfig",
    "GuardFired",
    "GuardFiredConfig",
    "NoSettings",
    "NumericClose",
    "Regex",
    "SchemaValid",
    "Status",
    "guard_matches",
]
