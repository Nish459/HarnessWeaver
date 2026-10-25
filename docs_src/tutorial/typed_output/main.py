import asyncio

from helpdesk.models import Ticket, Triage

import harnessweaver as hw


async def main() -> None:
    harness = hw.load("harness.yaml")
    ticket = Ticket(text="I was charged twice for my Pro plan. Refund one?")
    result = await harness.run("triage", ticket)
    print(result.status.value)
    if result.ok:
        triage = Triage.model_validate(result.output)
        print(f"{triage.category}, priority {triage.priority}: {triage.summary}")


if __name__ == "__main__":
    asyncio.run(main())
