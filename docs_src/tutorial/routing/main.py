import asyncio

import harnessweaver as hw
from harnessweaver.testing import render_trace

QUESTIONS = ["The dashboard is down, what do I do?", "How long does a refund take?"]


async def main() -> None:
    harness = hw.load("harness.yaml")
    for question in QUESTIONS:
        result = await harness.run("answer", question, principal="ann", tenant="acme")
        print(result.output)
        routing = [e for e in result.trace if e.source in ("harness.routing", "harness.decision")]
        print(render_trace(routing))


if __name__ == "__main__":
    asyncio.run(main())
