import asyncio

from helpdesk.models import Ticket

import harnessweaver as hw

TICKET = Ticket(text="The app crashes every time I log in since this morning's update.")


async def main() -> None:
    harness = hw.load("harness.yaml")

    result = await harness.run("triage", TICKET)
    print(f"{result.status.value}, cost ${result.cost_usd:.6f}")

    tight = await harness.run("triage", TICKET, budget={"max_model_calls": 1})
    if tight.error is not None:
        print(f"{tight.status.value} ({tight.error.details['code']}): {tight.error.message}")


if __name__ == "__main__":
    asyncio.run(main())
