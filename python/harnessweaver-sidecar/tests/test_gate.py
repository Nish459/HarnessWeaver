"""The token and the body cap come before any body is read (S6).

FastAPI reads and parses a body before it solves a route's dependencies, so a
dependency alone lets a peer without the token make harnessd buffer whatever it
sends. These tests drive the ASGI app directly to see every ``receive`` call, and
over a real local connection to see what uvicorn does with an unread body.
"""

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Message

from harnessweaver_sidecar.app import DEFAULT_MAX_BODY_BYTES, create_app
from harnessweaver_sidecar.main import load

DESK = Path(__file__).resolve().parent / "desk"
TOKEN = "sk-test-harnessd"
PROTECTED = "/v1/policy/evaluate"
INPUT_CHECK = b'{"principal": "alice", "tenant": "acme", "content": "hi"}'


def capped(max_body_bytes: int) -> FastAPI:
    """A harnessd over the help desk with a small body cap."""
    return create_app(load(DESK / "harness.yaml"), token=TOKEN, max_body_bytes=max_body_bytes)


async def request(
    app: FastAPI, path: str, chunks: list[bytes], *, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], Any, int]:
    """POST ``chunks`` as separate ASGI messages, as a chunked upload arrives.

    Returns:
        The status, the response headers, the parsed body and how many times the
        app called ``receive``.
    """
    reads = 0
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal reads
        reads += 1
        body = chunks[reads - 1] if reads <= len(chunks) else b""
        return {"type": "http.request", "body": body, "more_body": reads < len(chunks)}

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()
        ],
        "client": ("testclient", 1),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    answered = {name.decode(): value.decode() for name, value in start["headers"]}
    return start["status"], answered, json.loads(body), reads


BEARER = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer sk-test-wrong"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": "Bearer"},
    ],
)
@pytest.mark.parametrize(
    "path", [PROTECTED, "/v1/runs", "/v1/guards/input", "/v1/nope", "/docs", "/v1/health/"]
)
async def test_without_the_token_no_body_is_read(
    app: FastAPI, path: str, headers: dict[str, str]
) -> None:
    status, answered, body, reads = await request(app, path, [b"[" * 1024], headers=headers)
    assert status == 401
    assert answered["www-authenticate"] == "Bearer"
    assert body["code"] == "policy_denied"
    assert reads == 0


def test_a_malformed_body_without_the_token_is_refused_for_the_token(app: FastAPI) -> None:
    headers = {"Content-Type": "application/json"}
    response = TestClient(app).post(PROTECTED, content=b"[[[", headers=headers)
    assert response.status_code == 401


def test_health_stays_open(app: FastAPI) -> None:
    assert TestClient(app).get("/v1/health").status_code == 200


def test_a_body_at_the_cap_is_served_and_one_byte_over_is_not() -> None:
    at_the_cap = TestClient(capped(len(INPUT_CHECK)), headers=BEARER)
    assert at_the_cap.post("/v1/guards/input", content=INPUT_CHECK).status_code == 200
    over = TestClient(capped(len(INPUT_CHECK) - 1), headers=BEARER)
    response = over.post("/v1/guards/input", content=INPUT_CHECK)
    assert response.status_code == 413
    assert response.json()["code"] == "validation_failed"
    assert "input" not in response.json()["message"]  # never the content (R9)


@pytest.mark.anyio
async def test_a_chunked_body_stops_being_read_at_the_cap() -> None:
    chunks = [b"x" * 100] * 50
    status, _, body, reads = await request(capped(250), PROTECTED, chunks, headers=BEARER)
    assert status == 413
    assert body["type"] == "HTTPError"
    assert reads == 3


def test_the_cap_has_a_default(app: FastAPI) -> None:
    assert app.state.max_body_bytes == DEFAULT_MAX_BODY_BYTES


@contextmanager
def listening(app: FastAPI) -> Iterator[int]:
    """Serve ``app`` with uvicorn on a free local port; yields the port."""
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
    except PermissionError:
        sock.close()
        pytest.skip("this sandbox can't listen on a local port")
    server = uvicorn.Server(uvicorn.Config(app, log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    try:
        while not server.started and thread.is_alive():
            time.sleep(0.01)
        yield sock.getsockname()[1]
    finally:
        server.should_exit = True
        thread.join()


def test_over_a_socket_a_peer_without_the_token_is_answered_before_its_body_arrives(
    app: FastAPI,
) -> None:
    head = (
        f"POST {PROTECTED} HTTP/1.1\r\nHost: harnessd\r\nContent-Type: application/json\r\n"
        "Content-Length: 1000000000\r\n\r\n[[["
    )
    with listening(app) as port, socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
        peer.sendall(head.encode())
        assert peer.recv(4096).startswith(b"HTTP/1.1 401")


def test_over_a_socket_a_chunked_upload_over_the_cap_gets_413() -> None:
    head = (
        f"POST {PROTECTED} HTTP/1.1\r\nHost: harnessd\r\nContent-Type: application/json\r\n"
        f"Authorization: Bearer {TOKEN}\r\nTransfer-Encoding: chunked\r\n\r\n"
    )
    chunk = b"400\r\n" + b"x" * 1024 + b"\r\n"
    with (
        listening(capped(1024)) as port,
        socket.create_connection(("127.0.0.1", port), timeout=5) as peer,
    ):
        peer.sendall(head.encode() + chunk * 3)
        assert peer.recv(4096).startswith(b"HTTP/1.1 413")
