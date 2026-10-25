import asyncio

import harnessweaver as hw


async def main() -> None:
    harness = hw.load("harness.yaml")
    result = await harness.run("triage", "I was charged twice for my Pro plan. Refund one?")
    print(result.status.value)
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
