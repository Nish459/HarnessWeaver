import asyncio

from helpdesk.flows import answer

import harnessweaver as hw


async def main() -> None:
    harness = hw.load("harness.yaml")
    async with harness.session("answer", principal="ann", tenant="acme") as s:
        question = await s.guard("input", "How long does a refund take? I'm ann@example.com")
        print(question)
        print(await answer(s, str(question)))


if __name__ == "__main__":
    asyncio.run(main())
