import asyncio

from helpdesk.models import Ticket, Triage

import harnessweaver as hw
from harnessweaver.testing import render_trace


async def main() -> None:
    harness = hw.load("harness.yaml")
    ticket = Ticket(text="The app crashes every time I log in since this morning's update.")
    result = await harness.run("triage", ticket)
    print(result.status.value)
    if result.ok:
        triage = Triage.model_validate(result.output)
        print(f"{triage.category}, priority {triage.priority}: {triage.summary}")
    print(render_trace(result))


if __name__ == "__main__":
    asyncio.run(main())
