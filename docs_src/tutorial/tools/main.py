import asyncio

import harnessweaver as hw
from harnessweaver.testing import render_trace


async def main() -> None:
    harness = hw.load("harness.yaml")
    result = await harness.run("orders", "Where is my order A-1002?", principal="ann")
    print(result.output)
    tools = [e for e in result.trace if e.hook and e.hook.value.startswith("tool.")]
    print(render_trace(tools))


if __name__ == "__main__":
    asyncio.run(main())
