"""The ``evals`` module: datasets, graders, suite runs, baselines, online sampling and the
shadow-guard report (DESIGNS No. 23)."""

from harnessweaver.modules.evals.datasets import (
    build_grader,
    build_graders,
    load_dataset,
    read_dataset,
)
from harnessweaver.modules.evals.graders import (
    CitationPresent,
    Contains,
    Exact,
    FieldEquals,
    GuardFired,
    NumericClose,
    Regex,
    SchemaValid,
    Status,
)
from harnessweaver.modules.evals.judge import LlmJudgeGrader
from harnessweaver.modules.evals.online import install_online_evals
from harnessweaver.modules.evals.results import (
    compare,
    firings,
    online_shadow_report,
    sampled,
    shadow_report,
    summarize,
)
from harnessweaver.modules.evals.runner import (
    EVAL_PRINCIPAL,
    EvalTarget,
    run_suite,
    shadow_guards,
    suite_shadow_report,
)
from harnessweaver.modules.evals.values import json_equal, output_text, value_at

__all__ = [
    "EVAL_PRINCIPAL",
    "CitationPresent",
    "Contains",
    "EvalTarget",
    "Exact",
    "FieldEquals",
    "GuardFired",
    "LlmJudgeGrader",
    "NumericClose",
    "Regex",
    "SchemaValid",
    "Status",
    "build_grader",
    "build_graders",
    "compare",
    "firings",
    "install_online_evals",
    "json_equal",
    "load_dataset",
    "online_shadow_report",
    "output_text",
    "read_dataset",
    "run_suite",
    "sampled",
    "shadow_guards",
    "shadow_report",
    "suite_shadow_report",
    "summarize",
    "value_at",
]
