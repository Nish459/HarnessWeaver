import asyncio

import harnessweaver as hw

REQUESTS = ["Refund $40 on order A-1002, please.", "Refund $900 on order A-1001 now."]


async def main() -> None:
    harness = hw.load("harness.yaml")
    for request in REQUESTS:
        result = await harness.run("orders", request, principal="ann")
        if result.ok:
            print(f"completed: {result.output}")
        elif result.error is not None:
            print(f"{result.status.value} ({result.error.details['code']}): {result.error.message}")


if __name__ == "__main__":
    asyncio.run(main())
