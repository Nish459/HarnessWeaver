"""A plugin that breaks every conformance rule on purpose, to test the checks themselves."""

import itertools
from typing import Any

import anyio
from pydantic import BaseModel

import harnessweaver as hw
from harnessweaver.testing import AdapterSample

_counter = itertools.count()


@hw.provider(port="Guardrail", name="leaky", deterministic=True, latency_class="fast")
class LeakyGuard:
    """Puts the content it saw into its reason (breaks R9)."""

    async def check(self, content: str, env: hw.Envelope) -> hw.GuardResult:
        if "@" in content:
            return hw.GuardResult.block(f"found {content}")
        return hw.GuardResult.allow()


@hw.provider(port="Guardrail", name="moody", deterministic=True, latency_class="fast")
class MoodyGuard:
    """Claims to be deterministic but isn't."""

    def __init__(self) -> None:
        self.mood = next(_counter)

    async def check(self, content: str, env: hw.Envelope) -> hw.GuardResult:
        return hw.GuardResult.block("bad mood") if self.mood % 2 else hw.GuardResult.allow()


@hw.provider(port="Guardrail", name="slow", deterministic=True, latency_class="fast")
class SlowGuard:
    """Declares itself fast and isn't."""

    async def check(self, content: str, env: hw.Envelope) -> hw.GuardResult:
        await anyio.sleep(0.05)
        return hw.GuardResult.allow()


class Needs(BaseModel):
    endpoint: str


@hw.provider(port="Guardrail", name="needy", config=Needs)
class NeedsSettings:
    """Has a required setting and no sample."""

    def __init__(self, config: Needs) -> None:
        self.config = config

    async def check(self, content: str, env: hw.Envelope) -> hw.GuardResult:
        return hw.GuardResult.allow()


@hw.provider(port="Guardrail", name="wrong")
class WrongResult:
    """Returns something that isn't a GuardResult."""

    async def check(self, content: str, env: hw.Envelope) -> Any:
        return {"action": "allow"}


@hw.provider(port="ModelProvider", name="chatty", deterministic=True, latency_class="fast")
class ChattyModel:
    """A model provider that echoes the prompt into its error (breaks R9)."""

    async def generate(self, request: hw.ModelRequest, env: hw.Envelope) -> hw.ModelResponse:
        raise hw.errors.ProviderError(f"can't answer {request.messages[-1].content}")


@hw.middleware(hooks=["input.before"], fail_mode="closed")
async def confused(event: Any, env: hw.Envelope) -> Any:
    return "yes"


@hw.runner("sneaky", reaches=["run.start", "run.end"])
class SneakyRunner:
    """Calls a model without declaring the model hooks (breaks R4)."""

    async def execute(self, ctx: hw.RunContext, input: Any, resume: Any) -> Any:
        response = await ctx.generate(hw.ModelRequest(messages=(hw.Message.user("hi"),)))
        return response.text


@hw.adapter("unsampled", wraps=["builtins.object"], reaches=["model.before", "model.after"])
class UnsampledAdapter:
    def bind(self, target: Any, binding: Any) -> Any:
        return target


class _Target:
    pass


def _quiet_sample() -> AdapterSample:
    async def call(wrapped: Any) -> None:
        return None

    return AdapterSample(_Target(), call)


@hw.adapter(
    "quiet",
    wraps=["hw_badkit._Target"],
    reaches=["run.start", "model.before", "model.after", "run.end"],
    sample=_quiet_sample,
)
class QuietAdapter:
    """Declares hooks it never fires."""

    def bind(self, target: Any, binding: Any) -> Any:
        return target


plugin = hw.Plugin(
    namespace="badkit",
    version="0.0.1",
    providers=[LeakyGuard, MoodyGuard, SlowGuard, NeedsSettings, WrongResult, ChattyModel],
    middleware=[confused],
    runners=[SneakyRunner],
    adapters=[UnsampledAdapter, QuietAdapter],
    profiles={"missing": "no_such_profile.yaml"},
)
