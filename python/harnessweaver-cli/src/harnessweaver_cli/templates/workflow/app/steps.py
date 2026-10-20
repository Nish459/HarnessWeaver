"""The pipeline's steps, run by the ``workflow`` runner (DESIGNS No. 15).

Each handler is ``async (session, inputs) -> output``: ``inputs`` holds the run's
``input`` and the outputs of the steps it needs. Model calls go through the
session, so each is governed and budgeted. ``review`` is the reply step's
evaluator: ``True`` accepts the draft, a string sends it back as feedback.
"""

from typing import Any

import harnessweaver as hw

CATEGORIES = ("billing", "bug", "account", "other")


async def clean(s: hw.Session, inputs: dict[str, Any]) -> str:
    """Normalize the ticket's whitespace; no model call."""
    return " ".join(str(inputs["input"]).split())


async def classify(s: hw.Session, inputs: dict[str, Any]) -> str:
    """The ticket's category; an answer outside the list counts as ``other``."""
    answer = await s.generate(prompt="classify@1", ticket=inputs["clean"])
    category = str(answer).strip().lower()
    return category if category in CATEGORIES else "other"


async def summarize(s: hw.Session, inputs: dict[str, Any]) -> str:
    """One sentence about the ticket."""
    return str(await s.generate(prompt="summarize@1", ticket=inputs["clean"])).strip()


async def reply(s: hw.Session, inputs: dict[str, Any]) -> dict[str, Any]:
    """A reply draft; after a review, ``inputs["feedback"]`` says what to fix."""
    feedback = inputs.get("feedback")
    text = await s.generate(
        prompt="reply@1",
        category=inputs["classify"],
        summary=inputs["summarize"],
        feedback=f"Reviewer feedback: {feedback}" if feedback else "",
    )
    return {"category": inputs["classify"], "summary": inputs["summarize"], "reply": text}


async def review(s: hw.Session, output: dict[str, Any]) -> bool | str:
    """Accept a reply that names the ticket's category; otherwise say what's missing."""
    if output["category"] in str(output["reply"]).lower():
        return True
    return f"mention that this is a {output['category']} issue"
