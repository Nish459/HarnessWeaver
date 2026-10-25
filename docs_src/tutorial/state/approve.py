import asyncio
import sys

import harnessweaver as hw


async def main(run_id: str) -> None:
    async with hw.load("harness.yaml") as harness:
        waiting = await harness.result(run_id)
        request = waiting.approval
        if request is None:
            print(f"{waiting.status.value}: nothing to approve")
            return
        fiona = hw.Principal(id="fiona", roles=("finance",))
        result = await harness.approve(run_id, request.approval_id, "approve", approver=fiona)
    print(f"{result.status.value}: {result.output}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
