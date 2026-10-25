import asyncio

from helpdesk.models import Ticket, Triage

import harnessweaver as hw


async def main() -> None:
    harness = hw.load("harness.yaml")
    ticket = Ticket(text="I was charged twice for my Pro plan. Refund one? ann@example.com")
    result = await harness.run("triage", ticket)
    if result.ok:
        triage = Triage.model_validate(result.output)
        print(f"{triage.category}, priority {triage.priority}: {triage.summary}")
    print(result.status.value)
    for event in result.trace:
        if event.code:
            print(f"{event.source} ({event.code}): {event.reason}")


if __name__ == "__main__":
    asyncio.run(main())
