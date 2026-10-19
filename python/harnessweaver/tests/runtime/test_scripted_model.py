"""The offline ``scripted`` model provider in a running harness."""

from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.errors import ProviderError
from harnessweaver.modules.models import ScriptedModel

from .conftest import Builder, spec
from .l1_support import scripted

pytestmark = pytest.mark.anyio


async def test_the_scripted_model_follows_rules_then_replies(testkit: Any) -> None:
    model = ScriptedModel.of(
        "first",
        {"output": {"a": 1}},
        rules=[{"contains": "REFUND", "times": 1, "reply": {"tool_calls": [{"name": "refund"}]}}],
        repeat_last=False,
    )
    env = hw.Envelope.new(tenant="t", principal="p")

    def ask(text: str) -> hw.ModelRequest:
        return hw.ModelRequest(messages=(hw.Message.user(text),))

    refund = await model.generate(ask("please refund"), env)
    assert refund.tool_calls[0].id == "call_1"
    assert refund.finish_reason == "tool_calls"
    assert (await model.generate(ask("please refund"), env)).text == "first"
    structured = await model.generate(ask("x"), env)
    assert structured.output == {"a": 1}
    assert structured.text == '{"a": 1}'
    assert structured.usage.input_tokens == 1
    with pytest.raises(ProviderError, match="no reply left"):
        await model.generate(ask("x"), env)
    assert len(model.requests) == 4
    chunks = [
        c
        async for c in ScriptedModel.of({"text": "ab", "chunks": ["a", "b"]}).stream(ask("x"), env)
    ]
    assert [getattr(c, "delta", None) for c in chunks] == ["a", "b", None]
    with pytest.raises(ProviderError, match="fails"):
        await ScriptedModel.of({"fail": True}).generate(ask("x"), env)
    with pytest.raises(ValueError, match="replies or rules"):
        ScriptedModel.of()
    with pytest.raises(ValueError, match="invalid pattern"):
        ScriptedModel.of("x", rules=[{"matches": "(", "reply": {}}])
    matching = ScriptedModel.of(
        "x", rules=[{"matches": "^go$", "role": "user", "reply": {"text": "went"}}]
    )
    assert (await matching.generate(ask("go"), env)).text == "went"
    assert (await matching.generate(hw.ModelRequest(messages=()), env)).text == "x"


async def test_scripted_ignores_settings_meant_for_a_real_provider(build: Builder) -> None:
    harness = build(
        spec(
            models=scripted({"text": "offline"}, base_url="http://litellm:4000"),
            tasks={"t": {"runner": "direct"}},
        )
    )
    assert (await harness.run("t", "q")).output == "offline"
