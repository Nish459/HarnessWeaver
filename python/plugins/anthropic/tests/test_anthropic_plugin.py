"""The anthropic plugin against a mocked transport: no network, fake keys only (R14, S7)."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from anthropic import Anthropic, AsyncAnthropic

import harnessweaver as hw
from harnessweaver.core.registry import PluginCatalog, PluginSource
from harnessweaver.errors import ModelRefusal, ProviderError, RunBlocked, SpecError
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


REFUSAL = {"type": "refusal", "category": "cyber", "explanation": "a secret explanation"}
SPENT = hw.Usage(input_tokens=15, output_tokens=5)


def refused_stream(*blocks: str) -> httpx2.Response:
    """A streamed answer that ends in a refusal, after any text ``blocks``."""
    start = {**message(), "content": [], "stop_reason": None}
    events: list[dict[str, Any]] = [{"type": "message_start", "message": start}]
    for index, value in enumerate(blocks):
        events += [
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "text_delta", "text": value},
            },
            {"type": "content_block_stop", "index": index},
        ]
    events += [
        {
            "type": "message_delta",
            "delta": {"stop_reason": "refusal", "stop_sequence": None, "stop_details": REFUSAL},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]
    return sse(*events)


def stream_request() -> hw.ModelRequest:
    return hw.ModelRequest(model="m", messages=(hw.Message.user("x"),), stream=True)


async def collect(stream: Any, into: list[Any]) -> None:
    """Add each item of ``stream`` to ``into``, which keeps them if the stream raises."""
    async for item in stream:
        into.append(item)


@pytest.mark.anyio
async def test_a_refusal_reports_its_usage_without_its_text() -> None:
    server = Server(ok(message(text("partial"), stop="refusal", stop_details=REFUSAL)))
    with pytest.raises(ModelRefusal) as caught:
        await provider(server).generate(hw.ModelRequest(messages=(hw.Message.user("x"),)), ENV)
    assert caught.value.details == {"code": "model_refusal", "category": "cyber"}
    assert caught.value.response.usage == SPENT
    assert caught.value.response.text == ""
    assert "secret" not in caught.value.message  # R9


@pytest.mark.anyio
async def test_a_refused_stream_blocks_and_reports_its_usage() -> None:
    received: list[Any] = []
    stream = provider(Server(refused_stream("partial"))).stream(stream_request(), ENV)
    with pytest.raises(ModelRefusal) as caught:
        await collect(stream, received)
    assert [i.delta for i in received] == ["partial"]  # delivered before the signal arrived
    assert caught.value.response.usage == SPENT


@pytest.mark.anyio
async def test_hold_stream_delivers_nothing_from_a_refused_stream() -> None:
    received: list[Any] = []
    held = provider(Server(refused_stream("partial")), hold_stream=True)
    with pytest.raises(ModelRefusal):
        await collect(held.stream(stream_request(), ENV), received)
    assert received == []


@pytest.mark.anyio
async def test_hold_stream_releases_an_ordinary_answer_in_order() -> None:
    start = {**message(), "content": [], "stop_reason": None}
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
    items = [i async for i in provider(server, hold_stream=True).stream(stream_request(), ENV)]
    assert [getattr(i, "delta", None) for i in items[:-1]] == ["Hel", "lo"]
    final = items[-1]
    assert isinstance(final, hw.ModelResponse)
    assert final.text == "Hello"


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


CREDENTIAL_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_CONFIG_DIR",
    "ANTHROPIC_IDENTITY_TOKEN",
    "ANTHROPIC_IDENTITY_TOKEN_FILE",
    "ANTHROPIC_FEDERATION_RULE_ID",
    "ANTHROPIC_ORGANIZATION_ID",
    "ANTHROPIC_SERVICE_ACCOUNT_ID",
)
"""The variables the SDK reads credentials from, besides the profiles in its config directory."""


def no_credentials(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Take away every credential the SDK could find: its variables, and profiles on disk."""
    for name in CREDENTIAL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(home))  # the config directory is ~/.config/anthropic
    monkeypatch.setenv("APPDATA", str(home))  # or %APPDATA%\Anthropic on Windows


@pytest.mark.anyio
@pytest.mark.parametrize("streaming", [False, True])
async def test_no_credentials_says_what_to_set(
    streaming: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With nothing to authenticate with, the SDK raises a bare TypeError: say what to set."""
    no_credentials(tmp_path, monkeypatch)
    server = Server(ok(message(text("never sent"))))
    client = AsyncAnthropic(
        max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(server))
    )
    chat = AnthropicMessages(AnthropicMessagesConfig(), client=client)
    request = hw.ModelRequest(messages=(hw.Message.user("x"),))
    call = collect(chat.stream(request, ENV), []) if streaming else chat.generate(request, ENV)
    with pytest.raises(ProviderError, match="found no credentials: set ANTHROPIC_API_KEY"):
        await call
    assert server.requests == []


@pytest.mark.anyio
async def test_a_profile_that_cant_be_loaded_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_credentials(tmp_path, monkeypatch)
    monkeypatch.setenv("ANTHROPIC_PROFILE", "work")  # named, but there is no such profile
    monkeypatch.delenv(hw.ports.TEST_MODE_ENV)  # type: ignore[attr-defined]
    # The client fails as it is built, before any request; the address is a dead end anyway.
    chat = AnthropicMessages(AnthropicMessagesConfig(base_url="http://127.0.0.1:9"))
    with pytest.raises(ProviderError, match=r"^anthropic.messages: Config file not found.*'work'"):
        await chat.generate(hw.ModelRequest(messages=(hw.Message.user("x"),)), ENV)


@pytest.mark.anyio
async def test_other_type_errors_are_left_alone() -> None:
    async def create(**_: Any) -> Any:
        raise TypeError("a bug, not missing credentials")

    endpoint = SimpleNamespace(with_raw_response=SimpleNamespace(create=create))
    client = SimpleNamespace(api_key=FAKE_KEY, beta=SimpleNamespace(messages=endpoint))
    chat = AnthropicMessages(AnthropicMessagesConfig(), client=client)
    with pytest.raises(TypeError, match="a bug"):
        await chat.generate(hw.ModelRequest(messages=(hw.Message.user("x"),)), ENV)


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
async def test_a_refusal_ends_the_run_blocked_with_its_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = Server(ok(message(stop="refusal", stop_details=REFUSAL)))
    monkeypatch.setattr(AnthropicMessages, "_get_client", lambda self: server.async_client())
    app = harness(
        tmp_path,
        models={"provider": "anthropic.messages", "default": "strong"},
        tasks={"ask": {"runner": "direct"}},
    )
    result = await app.run("ask", "what is the answer?")
    assert result.status is hw.RunStatus.BLOCKED
    assert result.error is not None
    assert result.error.details["code"] == "model_refusal"
    assert result.error.details["category"] == "cyber"
    assert result.usage == SPENT
    assert [e for e in result.trace if e.code == "model_refusal"]  # R13


@pytest.mark.anyio
async def test_instrument_blocks_a_refusal(tmp_path: Path) -> None:
    server = Server(ok(message(stop="refusal", stop_details=REFUSAL)))
    client = harness(tmp_path).instrument(server.async_client())
    with pytest.raises(RunBlocked) as caught:
        await client.messages.create(
            model="m", max_tokens=1, messages=[{"role": "user", "content": "x"}]
        )
    assert caught.value.details["code"] == "model_refusal"


def test_instrument_blocks_a_refusal_on_a_sync_client(tmp_path: Path) -> None:
    server = Server(ok(message(stop="refusal", stop_details=REFUSAL)))
    client = harness(tmp_path).instrument(server.sync_client())
    with pytest.raises(RunBlocked) as caught:
        client.messages.create(model="m", max_tokens=1, messages=[{"role": "user", "content": "x"}])
    assert caught.value.details["code"] == "model_refusal"


@pytest.mark.anyio
async def test_instrument_refuses_streaming(tmp_path: Path) -> None:
    client = harness(tmp_path).instrument(Server(ok(message(text("x")))).async_client())
    with pytest.raises(SpecError, match="streaming"):
        await client.messages.create(model="m", max_tokens=1, messages=[], stream=True)
    with pytest.raises(SpecError, match="streaming"):
        client.messages.stream(model="m", max_tokens=1, messages=[])
