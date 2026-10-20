"""Samples and contract checks for ``Evaluator`` providers (graders)."""

from typing import Any

from harnessweaver.core.evals import EvalSample, Grade, GuardFiring
from harnessweaver.core.guards import GuardAction
from harnessweaver.core.runs import RunStatus
from harnessweaver.testing.conformance.common import expect
from harnessweaver.testing.samples import CANARY

__all__ = ["evaluator_contract", "sample_eval_samples"]


def sample_eval_samples() -> list[EvalSample]:
    """A completed structured run, a blocked one, and a cited text answer; each output
    holds the canary, which no reason may repeat (R9)."""
    schema: Any = {"type": "object", "properties": {"total": {"type": "number"}}}
    return [
        EvalSample(
            case="structured",
            task="t",
            input={"text": "invoice"},
            expect={"total": 50, "category": "billing"},
            output={"total": 50.0, "category": "billing", "note": CANARY},
            output_schema=schema,
        ),
        EvalSample(
            case="blocked",
            task="t",
            input={"text": CANARY},
            status=RunStatus.BLOCKED,
            error_code="guard_blocked",
            guards=(GuardFiring(guard="guardrails.input[pii]", action=GuardAction.BLOCK),),
        ),
        EvalSample(
            case="text",
            task="t",
            expect="refund",
            output=f"Refunds take five business days [kb-1]. {CANARY}",
        ),
    ]


def evaluator_contract(name: str, grades: list[Any]) -> None:
    """Every grade is a ``Grade`` with a score in [0, 1] whose reason holds no content."""
    for grade in grades:
        expect(isinstance(grade, Grade), f"{name} returned {type(grade).__name__}")
        Grade.model_validate(grade.model_dump())
        expect(0 <= grade.score <= 1, f"{name} scored outside [0, 1]")
        expect(CANARY not in (grade.reason or ""), f"{name}'s reason holds raw content (R9)")
