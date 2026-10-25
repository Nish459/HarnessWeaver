import asyncio

from helpdesk.models import Ticket

import harnessweaver as hw
from harnessweaver.testing import render_trace


async def main() -> None:
    async with hw.load("harness.yaml") as harness:
        ticket = Ticket(text="I was charged twice for my Pro plan. Refund one? ann@example.com")
        result = await harness.run("triage", ticket, principal="ann", tenant="acme")
    print(f"{result.status.value}, cost ${result.cost_usd:.6f} (known: {result.cost_known})")
    print(render_trace(result))


if __name__ == "__main__":
    asyncio.run(main())
