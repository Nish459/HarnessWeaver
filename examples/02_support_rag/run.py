"""Example 02 in the Session style: the app's own code, governed step by step.

HARNESSWEAVER_ENV=offline uv run python examples/02_support_rag/run.py
"""

import asyncio
from pathlib import Path

from support.flow import answer

import harnessweaver as hw

HERE = Path(__file__).resolve().parent
SPEC = HERE / "harness.yaml"
ORG = HERE.parent / "_org"  # where org://acme-baseline lives (or HARNESSWEAVER_PROFILE_PATH)


async def main() -> None:
    harness = hw.load(SPEC, profile_dirs=[ORG])
    customer = hw.Principal(id="gina", roles=("customer",))
    async with harness.session("support", principal=customer, tenant="globex") as s:
        reply = await answer(s, "The dashboard is down, what do I do?")
    print(f"intent: {reply.intent}")
    print(f"answer: {reply.answer}")
    print(f"status: {s.result.status.value if s.result else '?'}")


if __name__ == "__main__":
    asyncio.run(main())
