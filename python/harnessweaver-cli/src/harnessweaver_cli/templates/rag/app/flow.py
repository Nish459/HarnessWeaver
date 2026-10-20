"""The answer flow, run by the ``session`` runner: route, retrieve, answer with citations.

The app owns the steps; the session governs each one. ``decide`` fires
``route.decide``, ``fetch`` re-checks every passage's ACL before the model sees
it, and ``generate`` runs the output guards, so an uncited answer is repaired.
"""

from typing import Any

import harnessweaver as hw

NO_ANSWER = "I don't know; a person will follow up."


async def answer(s: hw.Session, question: str) -> dict[str, Any]:
    """Answer one question from the knowledge base.

    Returns:
        The topic it was routed to, the answer and the ids of the passages used.
    """
    route = await s.decide("topic", text=question)
    passages = await s.context("kb").fetch(question)
    if not passages:  # nothing the asker may see answers it: don't let the model guess
        return {"topic": route.choice, "answer": NO_ANSWER, "sources": []}
    sources = "\n".join(f"[{p.id}] {p.content}" for p in passages)
    text = await s.generate(
        prompt="answer@1", question=question, topic=route.choice, sources=sources
    )
    return {"topic": route.choice, "answer": text, "sources": [p.id for p in passages]}
