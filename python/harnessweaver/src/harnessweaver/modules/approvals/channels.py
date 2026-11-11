"""The built-in approval channels (DESIGNS No. 18)."""

import inspect
import os
import smtplib
import ssl
import sys
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
    "SmtpTransport",
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
            value = _required_env(variable)
            headers[header] = value
        body = request.model_dump_json().encode("utf-8")
        seconds = self.config.timeout.total_seconds()
        status, _ = await self.sender(self.config.url, body, headers, seconds)
        if not 200 <= status < 300:
            raise ProviderError(f"approvals: the webhook answered HTTP {status}")


# -- helpers shared by webhook and email -------------------------------------


def _required_env(name: str) -> str:
    """Read a required, non-empty environment variable (S1).

    Raises:
        ProviderError: If the variable isn't set or is empty.
    """
    value = os.environ.get(name)
    if not value:
        raise ProviderError(f"approvals: environment variable {name} isn't set")
    return value


# -- email channel -----------------------------------------------------------


type SmtpTransport = smtplib.SMTP
"""The SMTP class used by ``_send_smtp``; injectable for testing."""


class EmailConfig(_Config):
    """SMTP settings for the ``email`` approval channel.

    ``host``, ``port`` and ``starttls`` identify the server. Credentials
    come from environment variables named by ``login_env`` and
    ``password_env`` (S1); when both are absent, no authentication is
    attempted (for relay servers that use IP allowlisting).
    """

    host: str = Field(
        description="SMTP host to connect to.",
    )
    port: int = Field(
        default=587,
        ge=1,
        le=65535,
        description="SMTP port (587 for STARTTLS).",
    )
    starttls: bool = Field(
        default=True,
        description="Upgrade to TLS with STARTTLS.",
    )
    timeout: Duration = Field(
        default=timedelta(seconds=30),
        description="Connection and send timeout.",
    )
    login_env: str | None = Field(
        default="HARNESSWEAVER_EMAIL_LOGIN",
        description=(
            "Environment variable holding the SMTP login (S1). Set to null to skip authentication."
        ),
    )
    password_env: str | None = Field(
        default="HARNESSWEAVER_EMAIL_PASSWORD",
        description=(
            "Environment variable holding the SMTP password (S1). "
            "Set to null to skip authentication."
        ),
    )
    sender: str = Field(
        description="The From address on outgoing approval mails.",
    )
    recipients: tuple[str, ...] = Field(
        min_length=1,
        description="The To addresses that receive approval requests.",
    )


def _send_smtp(
    msg: EmailMessage,
    host: str,
    port: int,
    starttls: bool,
    timeout: float,
    login: str | None,
    password: str | None,
    smtp_class: type[smtplib.SMTP] = smtplib.SMTP,
) -> dict[str, tuple[int, bytes]]:
    """Connect, optionally STARTTLS, authenticate, send and quit.

    All blocking; the caller wraps this in ``anyio.to_thread`` (C3).
    Returns the dict of refused recipients from ``send_message``.

    Raises:
        OSError: On connection, TLS or send failures.
        smtplib.SMTPException: On protocol-level SMTP errors.
    """
    with smtp_class(host, port, timeout=timeout) as server:
        if starttls:
            ctx = ssl.create_default_context()
            server.starttls(context=ctx)
        if login is not None and password is not None:
            server.login(login, password)
        return server.send_message(msg)


@provider(
    port="ApprovalChannel",
    name="email",
    config=EmailConfig,
    latency_class="slow",
    sample={
        "host": "smtp.example.com",
        "sender": "harness@example.com",
        "recipients": ["approver@example.com"],
    },
)
class EmailChannel:
    """Sends each approval request by e-mail via SMTP (standard library only).

    The message names the task, the tool or output, the reason and how
    to answer; it never includes raw content (R9). The real transport
    refuses the network in test mode (R14). A failed send is traced as
    ``approval_notify_failed``, like any channel.

    Args:
        config: Validated ``EmailConfig``.
        transport: Injectable SMTP class for testing; defaults to
            ``smtplib.SMTP``. The class is instantiated inside a worker
            thread.
    """

    def __init__(
        self,
        config: EmailConfig,
        transport: type[smtplib.SMTP] | None = None,
    ) -> None:
        self.config = config
        self._smtp_class = transport or smtplib.SMTP

    def _build_message(
        self,
        request: ApprovalRequest,
        env: Envelope,
    ) -> EmailMessage:
        """Build a plain-text e-mail without raw content (R9).

        The message names the task, the tool (or notes an output
        approval), the reason and how to answer.
        """
        role_part = f" (role: {request.approver_role})" if request.approver_role else ""
        task_line = f"Task: {env.task}\n" if env.task else ""
        if request.tool is not None:
            what_line = f"Tool: {request.tool.name}\n"
        elif request.call is None:
            what_line = "Kind: output approval\n"
        else:
            what_line = ""
        expires_line = (
            f"Expires at: {request.expires_at.isoformat()}\n"
            if request.expires_at is not None
            else ""
        )
        # Sanitise reason for the Subject header (no CR/LF).
        safe_reason = request.reason.replace("\r", " ").replace("\n", " ")
        body = (
            f"Run {request.run_id} needs approval{role_part}.\n"
            f"\n"
            f"Approval ID: {request.approval_id}\n"
            f"{task_line}"
            f"{what_line}"
            f"Reason: {safe_reason}\n"
            f"{expires_line}"
            f"\n"
            f"To answer, call harness.approve("
            f"run_id={request.run_id!r}, "
            f"approval_id={request.approval_id!r}, "
            f"decision=..., approver=...).\n"
        )
        msg = EmailMessage()
        msg["Subject"] = f"Approval needed: {safe_reason}"
        msg["From"] = self.config.sender
        msg["To"] = ", ".join(self.config.recipients)
        msg.set_content(body)
        return msg

    async def notify(self, request: ApprovalRequest, env: Envelope) -> None:
        """Send the approval request by e-mail in a worker thread (C3).

        Raises:
            ProviderError: When a required env var is missing, the SMTP
                send fails, or some recipients were refused (R13).
        """
        login: str | None = None
        password: str | None = None
        if self.config.login_env is not None:
            login = _required_env(self.config.login_env)
        if self.config.password_env is not None:
            password = _required_env(self.config.password_env)
        msg = self._build_message(request, env)
        timeout = self.config.timeout.total_seconds()
        try:
            refused = await anyio.to_thread.run_sync(
                _send_smtp,
                msg,
                self.config.host,
                self.config.port,
                self.config.starttls,
                timeout,
                login,
                password,
                self._smtp_class,
            )
        except OSError as exc:
            raise ProviderError(
                f"approvals: email send failed ({type(exc).__name__}: {exc})"
            ) from exc
        if refused:
            raise ProviderError(f"approvals: {len(refused)} recipient(s) refused")
