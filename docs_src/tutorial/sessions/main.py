import asyncio

import harnessweaver as hw


async def main() -> None:
    harness = hw.load("harness.yaml")
    question = "How long does a refund take?"
    result = await harness.run("answer", question, principal="ann", tenant="acme")
    print(result.status.value)
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
