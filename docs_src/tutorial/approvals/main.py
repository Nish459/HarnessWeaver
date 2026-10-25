import asyncio

import harnessweaver as hw


async def main() -> None:
    harness = hw.load("harness.yaml")
    result = await harness.run("orders", "Refund $250 on order A-1001.", principal="ann")
    print(result.status.value)
    request = result.approval
    if request is None:
        return

    print(f"waiting for {request.approver_role}: {request.reason}")
    if request.call is not None:
        print(f"tool call: {request.call.name} {request.call.arguments}")

    fiona = hw.Principal(id="fiona", roles=("finance",))
    result = await harness.approve(result.run_id, request.approval_id, "approve", approver=fiona)
    print(result.status.value)
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
