"""Chat in the terminal, with answers streaming: HARNESSWEAVER_ENV=offline python -m app.main"""

import asyncio
from pathlib import Path

import harnessweaver as hw

SPEC = Path(__file__).resolve().parents[1] / "harness.yaml"


def ask() -> str:
    """One message from the terminal; the end of input (Ctrl-D) ends the chat."""
    try:
        return input("you: ").strip()
    except EOFError:
        return ""


async def main() -> None:
    async with hw.load(SPEC) as harness:  # background runs need an open harness
        # input() blocks, so it runs in a thread and the event loop stays free (C3).
        while (message := await asyncio.to_thread(ask)) not in ("", "quit"):
            run_id = await harness.submit("chat", message, principal="demo")
            print("bot: ", end="", flush=True)
            async for event in harness.stream(run_id):
                if event.type == "chunk" and event.chunk is not None:
                    print(event.chunk.delta, end="", flush=True)
            result = await harness.result(run_id)
            why = f": {result.error.message}" if result.error is not None else ""
            print("" if result.ok else f"[{result.status.value}{why}]")


if __name__ == "__main__":
    asyncio.run(main())
