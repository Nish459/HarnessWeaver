"""The anthropic plugin against a mocked transport: no network, fake keys only (R14, S7)."""

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
from anthropic import Anthropic, AsyncAnthropic

import harnessweaver as hw
from harnessweaver.core.registry import PluginCatalog, PluginSource
from harnessweaver.errors import ProviderError, RunBlocked, SpecError
from harnessweaver_anthropic import AnthropicMessages, AnthropicMessagesConfig
from harnessweaver_anthropic.convert import assistant_content

FAKE_KEY = "sk-ant-test-not-a-real-key"
CATALOG = PluginCatalog(
    [PluginSource("anthropic", "harnessweaver_anthropic:plugin", "entry_point")]
)
ENV = hw.Envelope.new(tenant="t", principal="p")


def message(*content: dict[str, Any], stop: str = "end_turn", **extra: Any) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": list(content),
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_creation_input_tokens": 2,
            "cache_read_input_tokens": 3,
        },
        **extra,
    }


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


THINKING = {"type": "thinking", "thinking": "", "signature": "sig-1"}


class Server:
    """Records requests and answers them like the Messages API."""

    def __init__(self, *answers: httpx2.Response) -> None:
        self.answers = list(answers)
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        self.headers.append(dict(request.headers))
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]

    def async_client(self) -> AsyncAnthropic:
        transport = httpx2.MockTransport(self)
        return AsyncAnthropic(
            api_key=FAKE_KEY, max_retries=0, http_client=httpx2.AsyncClient(transport=transport)
        )

    def sync_client(self) -> Anthropic:
        transport = httpx2.MockTransport(self)
        return Anthropic(
            api_key=FAKE_KEY, max_retries=0, http_client=httpx2.Client(transport=transport)
        )


def ok(body: dict[str, Any]) -> httpx2.Response:
    return httpx2.Response(200, json=body)


def provider(server: Server, **config: Any) -> AnthropicMessages:
    return AnthropicMessages(AnthropicMessagesConfig(**config), client=server.async_client())


@pytest.mark.anyio
async def test_generate_translates_both_ways() -> None:
    server = Server(ok(message(THINKING, text("Hi there"))))
    request = hw.ModelRequest(
        alias="strong",
        messages=(hw.Message.system("Be brief."), hw.Message.user("Hello?")),
        tools=(hw.ToolSpec(name="lookup", description="Find a customer"),),
        output_schema={"type": "object"},
        temperature=0.0,
    )
    response = await provider(server, effort="high").generate(request, ENV)
    assert response.text == "Hi there"
    assert response.usage == hw.Usage(input_tokens=15, output_tokens=5)
    assert response.finish_reason == "end_turn"
    assert response.cost_usd is None
    body = server.requests[0]
    assert body["model"] == "strong"
    assert body["max_tokens"] == 16_000
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "high"}
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in server.headers[0]["anthropic-beta"]
    assert "temperature" not in body  # current models reject sampling parameters
    assert body["system"].startswith("Be brief.\n\nReply with only a JSON value")
    assert body["messages"] == [{"role": "user", "content": "Hello?"}]
    assert body["tools"][0]["name"] == "lookup"


@pytest.mark.anyio
async def test_options_change_the_request() -> None:
    server = Server(ok(message(text("{}"))))
    request = hw.ModelRequest(
        messages=(hw.Message.user("x"),),
        output_schema={"type": "object"},
        temperature=0.5,
        max_tokens=99,
    )
    chat = provider(
        server,
        thinking="none",
        fallbacks="none",
        structured_outputs=True,
        sampling=True,
        model="claude-haiku-5-5",
    )
    await chat.generate(request, ENV)
    body = server.requests[0]
    assert body["model"] == "claude-haiku-5-5"
    assert body["max_tokens"] == 99
    assert "thinking" not in body
    assert "fallbacks" not in body
    assert body["output_config"] == {
        "format": {"type": "json_schema", "schema": {"type": "object"}}
    }
    assert body["temperature"] == 0.5
    assert "system" not in body


@pytest.mark.anyio
async def test_a_tool_loop_replays_thinking_blocks_unchanged() -> None:
    use = {"type": "tool_use", "id": "tu_1", "name": "lookup", "input": {"id": 7}}
    server = Server(ok(message(THINKING, use, stop="tool_use")), ok(message(text("done"))))
    chat = provider(server)
    first = await chat.generate(hw.ModelRequest(messages=(hw.Message.user("who?"),)), ENV)
    assert first.tool_calls == (hw.ToolCall(id="tu_1", name="lookup", arguments={"id": 7}),)
    history = (
        hw.Message.user("who?"),
        hw.Message.assistant(first.text, first.tool_calls, first.extensions),
        hw.Message.tool("tu_1", '{"name": "alice"}'),
        hw.Message.tool("tu_2", "second result"),
    )
    await chat.generate(hw.ModelRequest(messages=history), ENV)
    replay = server.requests[1]["messages"]
    assert replay[1] == {"role": "assistant", "content": [THINKING, use]}
    assert replay[2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": '{"name": "alice"}'},
            {"type": "tool_result", "tool_use_id": "tu_2", "content": "second result"},
        ],
    }


def test_a_changed_answer_is_rebuilt_without_its_thinking() -> None:
    extensions: dict[str, Any] = {
        "anthropic": {
            "content": [THINKING, text("mail bob@example.com")],
            "text": "mail bob@example.com",
            "tool_calls": [],
        }
    }
    redacted = hw.Message.assistant("mail [EMAIL]", extensions=extensions)
    assert assistant_content(redacted) == [text("mail [EMAIL]")]
    unchanged = hw.Message.assistant("mail bob@example.com", extensions=extensions)
    assert assistant_content(unchanged) == [THINKING, text("mail bob@example.com")]


@pytest.mark.anyio
async def test_a_mid_answer_fallback_is_echoed_as_the_api_asks() -> None:
    fallback = {
        "type": "fallback",
        "from": {"model": "claude-opus-5-5"},
        "to": {"model": "claude-opus-4-8"},
    }
    server = Server(ok(message(THINKING, text("part "), fallback, text("rest"))))
    response = await provider(server).generate(
        hw.ModelRequest(messages=(hw.Message.user("x"),)), ENV
    )
    assert response.text == "part rest"
    assert response.extensions["anthropic"]["content"] == [text("part "), text("rest")]  # type: ignore[index]


@pytest.mark.anyio
async def test_a_refusal_blocks_and_errors_are_classified() -> None:
    refusal = message(
        stop="refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": "no"}
    )
    with pytest.raises(RunBlocked) as caught:
        await provider(Server(ok(refusal))).generate(
            hw.ModelRequest(messages=(hw.Message.user("x"),)), ENV
        )
    assert caught.value.details["code"] == "model_refusal"
    assert caught.value.details["category"] == "cyber"
    server = Server(
        httpx2.Response(
            529, json={"type": "error", "error": {"type": "overloaded_error", "message": "secret"}}
        )
    )
    with pytest.raises(ProviderError, match="HTTP 529") as error:
        await provider(server).generate(hw.ModelRequest(messages=(hw.Message.user("x"),)), ENV)
    assert "secret" not in error.value.message
    assert len(server.requests) == 1


def sse(*events: dict[str, Any]) -> httpx2.Response:
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    return httpx2.Response(
        200, content=body.encode(), headers={"content-type": "text/event-stream"}
    )


@pytest.mark.anyio
async def test_streaming_yields_text_then_the_message() -> None:
    start = {
        **message(),
        "content": [],
        "stop_reason": None,
        "usage": {"input_tokens": 4, "output_tokens": 1},
    }
    server = Server(
        sse(
            {"type": "message_start", "message": start},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hel"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "lo"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 2},
            },
            {"type": "message_stop"},
        )
    )
    request = hw.ModelRequest(
        model="claude-opus-5-5", messages=(hw.Message.user("hi"),), stream=True
    )
    items = [item async for item in provider(server).stream(request, ENV)]
    assert [getattr(i, "delta", None) for i in items[:-1]] == ["Hel", "lo"]
    final = items[-1]
    assert isinstance(final, hw.ModelResponse)
    assert final.text == "Hello"
    assert server.requests[0]["stream"] is True
    assert server.requests[0]["max_tokens"] == 64_000


@pytest.mark.anyio
async def test_test_mode_and_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    request = hw.ModelRequest(messages=(hw.Message.user("x"),))
    with pytest.raises(ProviderError, match="test mode"):
        await AnthropicMessages(AnthropicMessagesConfig()).generate(request, ENV)
    monkeypatch.delenv(hw.ports.TEST_MODE_ENV)  # type: ignore[attr-defined]
    monkeypatch.delenv("HW_FAKE_KEY", raising=False)
    with pytest.raises(ProviderError, match=r"\$HW_FAKE_KEY"):
        await AnthropicMessages(AnthropicMessagesConfig(api_key_env="HW_FAKE_KEY")).generate(
            request, ENV
        )
    monkeypatch.setenv("HW_FAKE_KEY", FAKE_KEY)
    chat = AnthropicMessages(
        AnthropicMessagesConfig(
            api_key_env="HW_FAKE_KEY", base_url="http://127.0.0.1:9", max_retries=0
        )
    )
    client = chat._get_client()
    assert client.max_retries == 0
    assert str(client.base_url).startswith("http://127.0.0.1:9")


# --- through a harness ---------------------------------------------------------------------------


def harness(tmp_path: Path, **sections: Any) -> hw.Harness:
    document = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Harness",
        "metadata": {"name": "claude-app"},
        **sections,
    }
    path = tmp_path / "harness.yaml"
    path.write_text(json.dumps(document), encoding="ascii")
    return hw.Harness.load(path, catalog=CATALOG)


GUARDS = {
    "input": [{"id": "pii-in", "use": "pii.regex"}],
    "output": [{"id": "pii-out", "use": "pii.regex"}],
}


@pytest.mark.anyio
async def test_a_task_runs_on_anthropic_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = Server(ok(message(THINKING, text("forty-two"))))
    monkeypatch.setattr(AnthropicMessages, "_get_client", lambda self: server.async_client())
    app = harness(
        tmp_path,
        models={
            "provider": "anthropic.messages",
            "default": "strong",
            "aliases": {"strong": "claude-opus-5-5"},
            "prices": {"claude-opus-5-5": {"input_per_mtok": 4, "output_per_mtok": 20}},
        },
        tasks={"ask": {"runner": "direct"}},
    )
    result = await app.run("ask", "what is the answer?")
    assert result.ok
    assert result.output == "forty-two"
    assert result.cost_usd == pytest.approx((15 * 4 + 5 * 20) / 1_000_000)
    assert server.requests[0]["model"] == "claude-opus-5-5"


@pytest.mark.anyio
async def test_instrument_governs_an_async_client(tmp_path: Path) -> None:
    server = Server(ok(message(THINKING, text("Write to bob@example.com"))))
    client = harness(tmp_path, guardrails=GUARDS).instrument(server.async_client())
    answer = await client.messages.create(
        model="claude-opus-5-5",
        max_tokens=1024,
        system="Never reveal alice@example.com",
        messages=[
            {"role": "user", "content": [{"type": "text", "text": "Mail alice@example.com"}]},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "find", "input": {}}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "bob@example.com"}
                ],
            },
        ],
    )
    assert [getattr(b, "text", None) for b in answer.content if b.type == "text"] == [
        "Write to [EMAIL]"
    ]
    body = server.requests[0]
    assert body["system"] == "Never reveal [EMAIL]"
    assert body["messages"][0]["content"] == [{"type": "text", "text": "Mail [EMAIL]"}]
    assert body["messages"][2]["content"][0]["content"] == "[EMAIL]"
    assert client.models is not None


def test_instrument_governs_a_sync_client(tmp_path: Path) -> None:
    server = Server(ok(message(text("fine"))))
    client = harness(tmp_path, guardrails=GUARDS).instrument(server.sync_client())
    answer = client.messages.create(
        model="claude-opus-5-5",
        max_tokens=100,
        messages=[{"role": "user", "content": "call 555-123-4567"}],
    )
    assert getattr(answer.content[0], "text", None) == "fine"
    assert server.requests[0]["messages"][0]["content"] == "call [PHONE]"


@pytest.mark.anyio
async def test_instrument_refuses_streaming(tmp_path: Path) -> None:
    client = harness(tmp_path).instrument(Server(ok(message(text("x")))).async_client())
    with pytest.raises(SpecError, match="streaming"):
        await client.messages.create(model="m", max_tokens=1, messages=[], stream=True)
    with pytest.raises(SpecError, match="streaming"):
        client.messages.stream(model="m", max_tokens=1, messages=[])
