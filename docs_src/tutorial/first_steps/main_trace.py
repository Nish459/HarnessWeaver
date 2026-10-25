import asyncio

import harnessweaver as hw
from harnessweaver.testing import render_trace


async def main() -> None:
    harness = hw.load("harness.yaml")
    result = await harness.run("triage", "I was charged twice for my Pro plan. Refund one?")
    print(result.status.value)
    print(result.output)
    print(render_trace(result))


if __name__ == "__main__":
    asyncio.run(main())
