"""A model that declines still costs tokens: the run counts them, and then ends blocked."""

from collections.abc import AsyncIterator

import pytest

import harnessweaver as hw
from harnessweaver.errors import ModelRefusal, RunBlocked

from .conftest import Builder, scripted, spec

pytestmark = pytest.mark.anyio

SPENT = hw.ModelResponse(model="m", usage=hw.Usage(input_tokens=11, output_tokens=7), cost_usd=0.25)


class Declines:
    """A provider whose model declines, after streaming one chunk when asked to stream."""

    async def generate(self, request: hw.ModelRequest, env: hw.Envelope) -> hw.ModelResponse:
        raise ModelRefusal(response=SPENT)

    async def stream(
        self, request: hw.ModelRequest, env: hw.Envelope
    ) -> AsyncIterator[hw.StreamChunk | hw.ModelResponse]:
        yield hw.StreamChunk(index=0, delta="partial")
        raise ModelRefusal(response=SPENT)


def test_a_refusal_is_a_blocked_error_with_the_refusal_code() -> None:
    error = ModelRefusal(response=SPENT, category="cyber")
    assert isinstance(error, RunBlocked)
    assert error.response is SPENT
    info = error.to_info()
    assert info.code == hw.errors.ErrorCode.BLOCKED
    assert info.details == {"code": "model_refusal", "category": "cyber"}
    assert ModelRefusal().response == hw.ModelResponse()


@pytest.mark.parametrize("stream", [False, True], ids=["generate", "stream"])
async def test_a_refusal_counts_its_usage_and_is_traced(build: Builder, stream: bool) -> None:
    harness = build(spec(models=scripted({"text": "unused"})))
    session = harness.session()
    request = hw.ModelRequest(model="m", messages=(hw.Message.user("x"),), stream=stream)
    with pytest.raises(ModelRefusal):
        async with session as s:
            await s.run_context.generate(request, provider=Declines())
    result = session.result
    assert result is not None
    assert result.status is hw.RunStatus.BLOCKED
    assert result.usage.total_tokens == 18
    assert result.cost_usd == pytest.approx(0.25)
    assert [e.code for e in result.trace if e.code == "model_refusal"]
    assert [e for e in result.trace if e.source == "harness.budget"]


async def test_a_refusal_skips_model_after(build: Builder) -> None:
    rule = {"hook": "model.after", "outcome": "block", "code": "saw_the_answer"}
    harness = build(
        spec(
            models=scripted({"text": "unused"}),
            middleware=[{"use": "testkit.script", "rules": [rule]}],
        )
    )
    request = hw.ModelRequest(model="m", messages=(hw.Message.user("x"),))
    with pytest.raises(ModelRefusal) as caught:
        async with harness.session() as s:
            await s.run_context.generate(request, provider=Declines())
    assert caught.value.details["code"] == "model_refusal"
