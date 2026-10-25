import asyncio

import harnessweaver as hw


async def main() -> None:
    harness = hw.load("harness.yaml")
    result = await harness.run("triage", "I was charged twice for my Pro plan. Refund one?")
    print(result.status.value)
    print(result.output)
    print(f"tokens: {result.usage.input_tokens} in, {result.usage.output_tokens} out")
    print(f"cost: ${result.cost_usd:.6f}")


if __name__ == "__main__":
    asyncio.run(main())
