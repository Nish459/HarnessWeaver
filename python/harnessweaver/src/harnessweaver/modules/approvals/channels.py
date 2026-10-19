"""The built-in approval channels: ``memory``, ``callback``, ``console`` and ``webhook``."""

import inspect
import os
import sys
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from harnessweaver._imports import import_object
from harnessweaver.core.durations import Duration
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import ProviderError, SpecError
from harnessweaver.core.plugins import provider
from harnessweaver.core.runs import ApprovalRequest
from harnessweaver.modules.tools.transports import HttpSender, send_http

__all__ = [
    "CallbackChannel",
    "CallbackConfig",
    "ConsoleChannel",
    "ConsoleConfig",
    "MemoryChannel",
    "WebhookChannel",
    "WebhookConfig",
]


class _Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


@provider(port="ApprovalChannel", name="memory", deterministic=True, latency_class="fast")
class MemoryChannel:
    """Keeps every request in ``requests``, for tests and apps that poll (the default)."""

    def __init__(self) -> None:
        self.requests: list[ApprovalRequest] = []

    async def notify(self, request: ApprovalRequest, env: Envelope) -> None:
        self.requests.append(request)


class CallbackConfig(_Config):
    handler: str = Field(description="'module:function' called with the ApprovalRequest.")


@provider(
    port="ApprovalChannel",
    name="callback",
    config=CallbackConfig,
    latency_class="fast",
    sample={"handler": "builtins:id"},
)
class CallbackChannel:
    """Calls an app function, sync or async, with each request. It must not answer in-line.

    Raises:
        SpecError: At construction, if the handler can't be imported or isn't callable.
    """

    def __init__(self, config: CallbackConfig) -> None:
        handler: Any = import_object(config.handler, "approvals.handler")
        if not callable(handler):
            raise SpecError(f"approvals.handler: {config.handler!r} isn't callable")
        self.handler = handler

    async def notify(self, request: ApprovalRequest, env: Envelope) -> None:
        answer = self.handler(request)
        if inspect.isawaitable(answer):
            await answer


class ConsoleConfig(_Config):
    stream: Literal["stdout", "stderr"] = "stderr"


@provider(port="ApprovalChannel", name="console", config=ConsoleConfig, latency_class="fast")
class ConsoleChannel:
    """Writes one line per request to the terminal, for local development."""

    def __init__(self, config: ConsoleConfig | None = None) -> None:
        self.config = config or ConsoleConfig()

    async def notify(self, request: ApprovalRequest, env: Envelope) -> None:
        role = f" from {request.approver_role}" if request.approver_role else ""
        stream = sys.stdout if self.config.stream == "stdout" else sys.stderr
        stream.write(
            f"[harnessweaver] run {request.run_id} needs approval {request.approval_id}{role}: "
            f"{request.reason}\n"
        )
        stream.flush()


class WebhookConfig(_Config):
    url: str
    timeout: Duration = timedelta(seconds=10)
    headers_env: dict[str, str] = Field(
        default_factory=dict[str, str],
        description="Header name -> environment variable holding its value (S1).",
    )


@provider(
    port="ApprovalChannel",
    name="webhook",
    config=WebhookConfig,
    latency_class="slow",
    sample={"url": "https://approvals.example.com/hooks/harness"},
)
class WebhookChannel:
    """POSTs each request as JSON (the ``approval-request`` contract) to ``url``.

    In test mode it refuses to call out (R14).
    """

    def __init__(self, config: WebhookConfig, sender: HttpSender | None = None) -> None:
        self.config = config
        self.sender = sender or send_http

    async def notify(self, request: ApprovalRequest, env: Envelope) -> None:
        headers = {"Content-Type": "application/json"}
        for header, variable in self.config.headers_env.items():
            value = os.environ.get(variable)
            if value is None:
                raise ProviderError(f"approvals: environment variable {variable} isn't set")
            headers[header] = value
        body = request.model_dump_json().encode("utf-8")
        seconds = self.config.timeout.total_seconds()
        status, _ = await self.sender(self.config.url, body, headers, seconds)
        if not 200 <= status < 300:
            raise ProviderError(f"approvals: the webhook answered HTTP {status}")
