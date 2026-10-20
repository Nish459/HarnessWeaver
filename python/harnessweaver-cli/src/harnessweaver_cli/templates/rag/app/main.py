"""Ask one question: HARNESSWEAVER_ENV=offline python -m app.main"""

import asyncio
from pathlib import Path

import harnessweaver as hw

SPEC = Path(__file__).resolve().parents[1] / "harness.yaml"


async def main() -> None:
    harness = hw.load(SPEC)
    result = await harness.run("answer", "How long does a refund take?", principal="demo")
    print(f"status: {result.status.value}")
    print(f"output: {result.output}")


if __name__ == "__main__":
    asyncio.run(main())
