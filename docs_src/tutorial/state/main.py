import asyncio

import harnessweaver as hw


async def main() -> str:
    async with hw.load("harness.yaml") as harness:
        result = await harness.run("orders", "Refund $250 on order A-1001.", principal="ann")
    print(f"{result.status.value}: {result.run_id}")
    return result.run_id


if __name__ == "__main__":
    asyncio.run(main())
