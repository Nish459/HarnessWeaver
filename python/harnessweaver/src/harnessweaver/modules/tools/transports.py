"""How a manifest's tool is reached: ``native``, ``http`` or ``code`` (governor step 8).

Every transport gets an idempotency key that stays the same when a run resumes and
repeats a call (``<run_id>:<call digest>``), so the tool's owner can drop the
repeat: native handlers that take an ``idempotency_key`` argument receive it, and
http tools get an ``Idempotency-Key`` header.
"""

import functools
import inspect
import json
import os
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import anyio.to_thread
from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from harnessweaver.core.errors import ProviderError, ToolError
from harnessweaver.core.manifests import ToolManifest
from harnessweaver.core.ports import Sandbox, network_allowed
from harnessweaver.core.tools import SandboxResult

__all__ = ["HttpSender", "NativeHandler", "call_code", "call_http", "call_native", "send_http"]

type HttpSender = Callable[[str, bytes, Mapping[str, str], float], Awaitable[tuple[int, bytes]]]
"""Sends one POST: ``(url, body, headers, timeout_seconds) -> (status, body)``."""


class NativeHandler:
    """A ``native`` tool's function, sync or async, called with the arguments as keywords."""

    def __init__(self, function: Callable[..., Any]) -> None:
        self.function = function
        parameters = inspect.signature(function).parameters
        self.takes_key = "idempotency_key" in parameters or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
        )
        self.is_async = inspect.iscoroutinefunction(function)

    async def __call__(self, args: Mapping[str, JsonValue], key: str) -> JsonValue:
        kwargs: dict[str, Any] = dict(args)
        if self.takes_key:
            kwargs["idempotency_key"] = key
        if self.is_async:
            value = await self.function(**kwargs)
        else:
            value = await anyio.to_thread.run_sync(functools.partial(self.function, **kwargs))
        return to_jsonable_python(value)


async def call_native(handler: NativeHandler, args: Mapping[str, JsonValue], key: str) -> JsonValue:
    return await handler(args, key)


def _post(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


async def send_http(
    url: str, body: bytes, headers: Mapping[str, str], seconds: float
) -> tuple[int, bytes]:
    """The default sender: the standard library, in a worker thread (C3).

    Raises:
        ProviderError: In test mode, which allows no network (R14).
    """
    if not network_allowed():
        raise ProviderError("test mode: http tools don't call out (R14)")
    return await anyio.to_thread.run_sync(_post, url, body, headers, seconds)


async def call_http(
    manifest: ToolManifest, args: Mapping[str, JsonValue], key: str, sender: HttpSender
) -> JsonValue:
    """POST the arguments as JSON; the JSON reply is the output.

    Raises:
        ToolError: For a non-2xx status or a reply that isn't JSON.
    """
    spec = manifest.spec
    headers = {"Content-Type": "application/json", "Idempotency-Key": key}
    for header, variable in spec.headers_env.items():
        value = os.environ.get(variable)
        if value is None:
            raise ToolError(f"tool {manifest.name}: environment variable {variable} isn't set")
        headers[header] = value
    body = json.dumps(dict(args)).encode("utf-8")
    assert spec.url is not None  # the manifest model requires it for http
    status, reply = await sender(spec.url, body, headers, spec.timeout.total_seconds())
    if not 200 <= status < 300:
        raise ToolError(f"tool {manifest.name} answered HTTP {status}")
    if not reply:
        return None
    try:
        return json.loads(reply)
    except ValueError:
        raise ToolError(f"tool {manifest.name} didn't answer with JSON") from None


async def call_code(
    manifest: ToolManifest, args: Mapping[str, JsonValue], sandbox: Sandbox
) -> SandboxResult:
    """Run the code in ``code_arg`` in the sandbox; the other arguments are its inputs (S4).

    Raises:
        ToolError: When the code argument is missing or isn't a string.
    """
    spec = manifest.spec
    code = args.get(spec.code_arg)
    if not isinstance(code, str):
        raise ToolError(f"tool {manifest.name} needs its code in the {spec.code_arg!r} argument")
    inputs = {name: value for name, value in args.items() if name != spec.code_arg}
    return await sandbox.run(code, inputs, spec.limits)
