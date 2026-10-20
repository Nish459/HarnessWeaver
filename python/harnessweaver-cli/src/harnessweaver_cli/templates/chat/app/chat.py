"""One chat turn, run by the ``session`` runner.

The conversation lives in ``s.memory``, which the harness keeps per tenant and
principal, so each user has their own history and nobody reads another's. The
answer streams (``stream=True``): each chunk passes the ``stream`` guards as it
arrives, and a chunk that leaks a secret cuts the stream there.
"""

from typing import Any

import harnessweaver as hw

SYSTEM = "You are a friendly assistant. Keep answers short."
TURNS_KEPT = 10
"""How many messages of history go back to the model."""


async def reply(s: hw.Session, message: str) -> str:
    """Answer one message, with the conversation so far."""
    history: list[Any] = await s.memory.get("history") or []
    messages = [
        hw.Message.system(SYSTEM),
        *(hw.Message.model_validate(m) for m in history),
        hw.Message.user(message),
    ]
    answer = str(await s.generate(messages=messages, stream=True))
    history += [
        hw.Message.user(message).model_dump(mode="json"),
        hw.Message.assistant(answer).model_dump(mode="json"),
    ]
    await s.memory.put("history", history[-TURNS_KEPT:])
    return answer
