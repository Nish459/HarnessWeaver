"""``monty.sandbox``: run code-executing tools in pydantic-monty (S4, DESIGNS No. 17).

Monty is a Python interpreter that runs in separate worker processes. Sandboxed
code gets the tool's other arguments as globals and returns its last
expression's value; it can't open host files, reach the network or read the
environment, and the manifest's ``limits`` cap its time and memory. A tool names
it with ``sandbox: monty`` (short for ``monty.sandbox``).
"""

from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue
from pydantic_core import to_jsonable_python

import harnessweaver as hw
from harnessweaver.core.durations import Duration

__all__ = ["MontySandbox", "MontySandboxConfig"]


class MontySandboxConfig(BaseModel):
    """Extra settings for ``monty.sandbox``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    grace: Duration = timedelta(seconds=2)
    """How long past a run's time limit the worker may take before it is killed."""


def _last_line(error: BaseException) -> str:
    lines = [line for line in str(error).splitlines() if line.strip()]
    return lines[-1] if lines else type(error).__name__


def _jsonable(value: Any) -> JsonValue:
    try:
        return to_jsonable_python(value)
    except Exception:  # an object JSON can't hold: describe it instead of failing the tool
        return repr(value)


@hw.provider(
    port="Sandbox",
    name="monty.sandbox",
    config=MontySandboxConfig,
    deterministic=False,
    latency_class="slow",
)
class MontySandbox:
    """Each run gets a fresh worker process, so no state leaks from one call to the next."""

    def __init__(self, config: MontySandboxConfig | None = None) -> None:
        self.config = config or MontySandboxConfig()

    async def run(
        self, code: str, inputs: dict[str, JsonValue], limits: hw.SandboxLimits
    ) -> hw.SandboxResult:
        # Imported on first use, so the plugin stays inert until a spec uses it (S8).
        from pydantic_monty import (
            AsyncMonty,
            CollectString,
            MontyCrashedError,
            MontyError,
            MontySyntaxError,
        )

        seconds = limits.timeout.total_seconds()
        printed = CollectString(max_bytes=limits.max_output_bytes)
        pool = AsyncMonty(
            min_processes=1,
            max_processes=1,
            request_timeout=seconds + self.config.grace.total_seconds(),
        )
        checkout = {"max_feed_duration_secs": seconds, "max_memory": limits.max_memory_mb << 20}
        try:
            async with pool, pool.checkout(limits=checkout) as session:  # type: ignore[arg-type]
                value = await session.feed_run(code, inputs=dict(inputs), print_callback=printed)
        except MontyCrashedError:
            error = "SandboxCrashed: the sandbox stopped (time or memory limit)"
            return hw.SandboxResult(error=error, stdout=printed.output)
        except MontySyntaxError as exc:
            return hw.SandboxResult(error=f"SyntaxError: {_last_line(exc)}", stdout=printed.output)
        except MontyError as exc:
            return hw.SandboxResult(error=_last_line(exc), stdout=printed.output)
        return hw.SandboxResult(value=_jsonable(value), stdout=printed.output)
