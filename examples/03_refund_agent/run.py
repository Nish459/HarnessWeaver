"""Example 03 in the Run style: ``harness.run()``, then a finance approval.

    HARNESSWEAVER_ENV=offline uv run python examples/03_refund_agent/run.py

The app asks for a refund; the harness runs the agent, which looks the order up
and asks to refund 250 USD. That is over the manifest's 100 USD threshold, so the
run waits for finance. Once finance approves, the agent continues from where it
stopped and only the approved call runs.
"""

import asyncio
from pathlib import Path

import harnessweaver as hw

HERE = Path(__file__).resolve().parent
SPEC = HERE / "harness.yaml"
ORG = HERE.parent / "_org"  # where org://acme-baseline lives (or HARNESSWEAVER_PROFILE_PATH)

CUSTOMER = hw.Principal(id="casey", roles=("customer",))
FINANCE = hw.Principal(id="fran", roles=("finance",))


async def main() -> hw.RunResult:
    """Ask for a full refund, approve it as finance, and print what happened."""
    harness = hw.load(SPEC, profile_dirs=[ORG])
    request = "Refund order A-1001 in full, it never arrived."
    result = await harness.run("refund", request, principal=CUSTOMER, tenant="acme")
    print(f"status: {result.status.value}")
    if result.approval is not None:
        print(f"waiting for {result.approval.approver_role}: {result.approval.reason}")
        result = await harness.approve(result.run_id, result.approval.approval_id, approver=FINANCE)
        print(f"after approval: {result.status.value}: {result.output}")
    return result


if __name__ == "__main__":
    asyncio.run(main())
