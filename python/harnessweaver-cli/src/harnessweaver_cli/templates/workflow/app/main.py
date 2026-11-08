"""Triage one ticket: HARNESSWEAVER_ENV=offline python -m app.main"""

import asyncio
from pathlib import Path

import harnessweaver as hw

SPEC = Path(__file__).resolve().parents[1] / "harness.yaml"


async def main() -> None:
    harness = hw.load(SPEC)
    ticket = "I was   charged twice for my Pro plan this month."
    result = await harness.run("triage", ticket, principal="demo")
    print(f"status: {result.status.value}")
    print(f"output: {result.output}")
    if result.error is not None:  # why the run didn't complete
        print(f"error: {result.error.code.value}: {result.error.message}")


if __name__ == "__main__":
    asyncio.run(main())
