"""The answer task: our own steps, each one governed by the harness."""

import harnessweaver as hw


async def answer(s: hw.Session, question: str) -> str:
    """Answer a customer's question in the support desk's voice."""
    return await s.generate(prompt="answer@1", question=question)
