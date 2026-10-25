"""The answer task: our own steps, each one governed by the harness."""

import harnessweaver as hw

OUTAGE_REPLY = "We know about the outage and are fixing it. Updates: status.acme.example"


async def answer(s: hw.Session, question: str) -> str:
    """Answer a customer's question in the support desk's voice."""
    route = await s.decide("intent", text=question)
    if route.choice == "outage":
        return OUTAGE_REPLY
    return await s.generate(prompt="answer@1", question=question)
