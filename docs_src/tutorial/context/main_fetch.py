import asyncio

import harnessweaver as hw


async def main() -> None:
    harness = hw.load("harness.yaml")
    question = "How fast does support reply to a refund question?"
    for tenant in ("acme", "globex"):
        async with harness.session("answer", principal="ann", tenant=tenant) as s:
            items = await s.context("help").fetch(question)
            print(tenant, [item.id for item in items])


if __name__ == "__main__":
    asyncio.run(main())
