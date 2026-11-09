"""The built-in approval channels: ``memory``, ``callback``, ``console``, ``webhook`` and ``email``."""

import inspect
import os
import smtplib
import sys
from collections.abc import Callable
from datetime import timedelta
from email.message import EmailMessage
from typing import Any, Literal

import anyio.to_thread
from pydantic import BaseModel, ConfigDict, Field

from harnessweaver._imports import import_object
from harnessweaver.core.durations import Duration
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import ProviderError, SpecError
from harnessweaver.core.plugins import provider
from harnessweaver.core.ports import network_allowed
from harnessweaver.core.runs import ApprovalRequest
from harnessweaver.modules.tools.transports import HttpSender, send_http

__all__ = [
    "CallbackChannel",
    "CallbackConfig",
    "ConsoleChannel",
    "ConsoleConfig",
    "EmailChannel",
    "EmailConfig",
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


type SmtpSender = Callable[[EmailMessage, str, int, bool, str, str], None]
"""Sends one e-mail: ``(msg, host, port, starttls, login_env, password_env) -> None``."""


class EmailConfig(_Config):
    """SMTP settings for the ``email`` approval channel.

    Credentials come from the environment (S1): ``login_env`` and ``password_env``
    name the variables that hold the SMTP username and password.
    """

    host_env: str = Field(
        default="HARNESSWEAVER_EMAIL_HOST",
        description="Environment variable holding the SMTP host.",
    )
    port: int = Field(default=587, description="SMTP port (587 for STARTTLS).")
    starttls: bool = Field(default=True, description="Upgrade to TLS with STARTTLS.")
    login_env: str = Field(
        default="HARNESSWEAVER_EMAIL_LOGIN",
        description="Environment variable holding the SMTP login (S1).",
    )
    password_env: str = Field(
        default="HARNESSWEAVER_EMAIL_PASSWORD",
        description="Environment variable holding the SMTP password (S1).",
    )
    sender: str = Field(
        default="harnessweaver@example.com",
        description="The From address on outgoing approval mails.",
    )
    recipients: list[str] = Field(
        description="The To addresses that receive approval requests.",
    )


def _send_smtp(
    msg: EmailMessage,
    host: str,
    port: int,
    starttls: bool,
    login: str,
    password: str,
) -> None:
    """Connect, optionally STARTTLS, authenticate, send, quit -- all blocking (C3 wrapper)."""
    with smtplib.SMTP(host, port) as server:
        if starttls:
            server.starttls()
        server.login(login, password)
        server.send_message(msg)


@provider(
    port="ApprovalChannel",
    name="email",
    config=EmailConfig,
    latency_class="slow",
    sample={
        "sender": "harness@example.com",
        "recipients": ["approver@example.com"],
    },
)
class EmailChannel:
    """Sends each approval request as an e-mail via SMTP, using only the standard library.

    The message names the task, the tool or output, the reason and how to answer;
    it never includes raw content (R9). In test mode it refuses the network (R14).
    A failed send is traced as ``approval_notify_failed``, like any channel.
    """

    def __init__(
        self,
        config: EmailConfig,
        sender: SmtpSender | None = None,
    ) -> None:
        self.config = config
        self._send = sender or _send_smtp

    def _build_message(self, request: ApprovalRequest) -> EmailMessage:
        """Build a plain-text e-mail describing the approval request without raw content (R9)."""
        role = f" (role: {request.approver_role})" if request.approver_role else ""
        tool_line = f"Tool: {request.tool.name}\n" if request.tool is not None else ""
        expires = (
            f"Expires at: {request.expires_at.isoformat()}\n"
            if request.expires_at is not None
            else ""
        )
        body = (
            f"Run {request.run_id} needs approval{role}.\n"
            f"\n"
            f"Approval ID: {request.approval_id}\n"
            f"{tool_line}"
            f"Reason: {request.reason}\n"
            f"{expires}"
            f"\n"
            f"To answer, call harness.approve(run_id={request.run_id!r}, "
            f"approval_id={request.approval_id!r}, decision=..., approver=...).\n"
        )
        msg = EmailMessage()
        msg["Subject"] = f"Approval needed: {request.reason}"
        msg["From"] = self.config.sender
        msg["To"] = ", ".join(self.config.recipients)
        msg.set_content(body)
        return msg

    def _env(self, name: str) -> str:
        """Read a required environment variable (S1).

        Raises:
            ProviderError: If the variable isn't set.
        """
        value = os.environ.get(name)
        if value is None:
            raise ProviderError(f"approvals: environment variable {name} isn't set")
        return value

    async def notify(self, request: ApprovalRequest, env: Envelope) -> None:
        """Send the approval request by e-mail in a worker thread (C3).

        Raises:
            ProviderError: In test mode (R14), or when a required env var is missing,
                or when the SMTP send fails.
        """
        if not network_allowed():
            raise ProviderError("test mode: the email channel doesn't send mail (R14)")
        host = self._env(self.config.host_env)
        login = self._env(self.config.login_env)
        password = self._env(self.config.password_env)
        msg = self._build_message(request)
        try:
            await anyio.to_thread.run_sync(
                self._send, msg, host, self.config.port, self.config.starttls, login, password
            )
        except smtplib.SMTPException as exc:
            raise ProviderError(f"approvals: email send failed ({exc})") from exc
