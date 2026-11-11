"""Approval channels tell approvers a run waits; a failing one is traced (DESIGNS No. 18)."""

import json
import smtplib
from collections.abc import Mapping
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.modules.approvals import (
    EmailChannel,
    EmailConfig,
    WebhookChannel,
    WebhookConfig,
)
from harnessweaver.testing.samples import sample_approval_request

from .conftest import Builder
from .governance_support import call, refund_tool, tool_spec

pytestmark = pytest.mark.anyio

NOTIFIED: list[hw.ApprovalRequest] = []


def notify(request: hw.ApprovalRequest) -> None:
    NOTIFIED.append(request)


async def notify_async(request: hw.ApprovalRequest) -> None:
    NOTIFIED.append(request)


def _spec(tmp_path: Path, approvals: dict[str, Any]) -> dict[str, Any]:
    refund_tool(tmp_path, approval={"when": "true", "approver_role": "finance"})
    return tool_spec(
        call("refund_payment", amount_usd=5), tools=["refund_payment"], approvals=approvals
    )


@pytest.mark.parametrize("handler", ["notify", "notify_async"])
async def test_a_callback_hears_about_each_request(
    build: Builder, tmp_path: Path, testkit: Any, monkeypatch: pytest.MonkeyPatch, handler: str
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    NOTIFIED.clear()
    path = f"{__name__}:{handler}"
    result = await build(_spec(tmp_path, {"use": "callback", "handler": path}), tools=None).run(
        "t", "go"
    )
    assert result.approval is not None
    assert [r.approval_id for r in NOTIFIED] == [result.approval.approval_id]


async def test_the_console_channel_writes_one_line(
    build: Builder, tmp_path: Path, testkit: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    result = await build(_spec(tmp_path, {"use": "console"}), tools=None).run("t", "go")
    assert result.approval is not None
    line = capsys.readouterr().err
    assert f"run {result.run_id} needs approval {result.approval.approval_id} from finance" in line


class _Hook:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.bodies: list[dict[str, Any]] = []

    async def __call__(
        self, url: str, body: bytes, headers: Mapping[str, str], seconds: float
    ) -> tuple[int, bytes]:
        self.bodies.append(json.loads(body))
        return self.status, b""


async def test_the_webhook_posts_the_request() -> None:
    hook = _Hook()
    channel = WebhookChannel(WebhookConfig(url="https://approvals.example.com/hook"), sender=hook)
    request = hw.ApprovalRequest(
        approval_id="apr_1",
        run_id="run_1",
        reason="needs finance",
        requested_at=hw.FakeClock().now(),
    )
    await channel.notify(request, hw.Envelope.new(tenant="t", principal="p"))
    assert hook.bodies[0]["approval_id"] == "apr_1"
    failing = WebhookChannel(
        WebhookConfig(url="https://approvals.example.com/hook"), sender=_Hook(500)
    )
    with pytest.raises(hw.errors.ProviderError, match="HTTP 500"):
        await failing.notify(request, hw.Envelope.new(tenant="t", principal="p"))


# -- email channel ----------------------------------------------------------


class _FakeSMTP:
    """A fake ``smtplib.SMTP`` that records calls instead of connecting.

    Injected as ``transport`` so the real connect/STARTTLS/login/send path
    is exercised without a network (issue 12).
    """

    host: str
    port: int
    timeout: float | None
    starttls_called: bool = False
    login_user: str | None = None
    login_password: str | None = None
    sent: list[EmailMessage]
    refused: dict[str, tuple[int, bytes]]

    def __init__(
        self,
        host: str = "",
        port: int = 0,
        *,
        timeout: float | None = None,
        fail_connect: bool = False,
        fail_send: bool = False,
        refused: dict[str, tuple[int, bytes]] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._fail_connect = fail_connect
        self._fail_send = fail_send
        self.refused = refused or {}
        self.starttls_called = False
        self.login_user = None
        self.login_password = None
        self.sent = []
        if fail_connect:
            raise ConnectionRefusedError(61, "Connection refused")

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def starttls(self, *, context: Any = None) -> None:
        """Record STARTTLS; verify a real ssl context was passed."""
        self.starttls_called = True
        self.starttls_context = context

    def login(self, user: str, password: str) -> None:
        """Record login credentials."""
        self.login_user = user
        self.login_password = password

    def send_message(self, msg: EmailMessage) -> dict[str, tuple[int, bytes]]:
        """Record the message; optionally simulate a send failure."""
        if self._fail_send:
            raise smtplib.SMTPDataError(451, b"Temporary failure")
        self.sent.append(msg)
        return self.refused


# Keep a reference to the last _FakeSMTP instance for assertions.
_last_fake: _FakeSMTP | None = None


def _make_fake_smtp(**defaults: Any) -> type:
    """Return a class whose ``__init__`` builds a ``_FakeSMTP`` and stashes it."""

    class _Wrapper(_FakeSMTP):
        def __init__(self, host: str = "", port: int = 0, **kw: Any) -> None:
            global _last_fake
            merged = {**defaults, **kw}
            super().__init__(host, port, **merged)
            _last_fake = self

    return _Wrapper


def _email_request() -> hw.ApprovalRequest:
    """An approval request with a tool, based on the conformance sample."""
    return sample_approval_request().model_copy(update={"tool": hw.ToolInfo(name="refund_payment")})


def _email_env(mp: pytest.MonkeyPatch) -> None:
    """Set the SMTP credential env vars for tests that need them."""
    mp.setenv("HARNESSWEAVER_EMAIL_LOGIN", "bot@example.com")
    mp.setenv("HARNESSWEAVER_EMAIL_PASSWORD", "sk-test-secret")


async def test_the_email_channel_sends_a_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The channel connects, STARTTLS, logs in, sends and records the message."""
    _email_env(monkeypatch)
    fake_cls = _make_fake_smtp()
    config = EmailConfig(
        host="smtp.example.com",
        sender="harness@example.com",
        recipients=("approver@example.com", "lead@example.com"),
    )
    channel = EmailChannel(config, transport=fake_cls)
    request = _email_request()
    env = hw.Envelope.new(tenant="t", principal="p", task="refunds")
    await channel.notify(request, env)
    assert _last_fake is not None
    assert _last_fake.host == "smtp.example.com"
    assert _last_fake.port == 587
    assert _last_fake.starttls_called
    assert _last_fake.starttls_context is not None
    assert _last_fake.login_user == "bot@example.com"
    assert _last_fake.login_password == "sk-test-secret"
    assert len(_last_fake.sent) == 1
    msg = _last_fake.sent[0]
    assert msg["To"] == "approver@example.com, lead@example.com"
    assert msg["From"] == "harness@example.com"
    assert msg["Subject"] == ("Approval needed: refunds over 100 USD need finance")
    body = msg.get_content()
    assert "Task: refunds" in body
    assert "Tool: refund_payment" in body
    assert _email_request().approval_id in body
    assert "harness.approve" in body


async def test_the_email_channel_without_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A relay with no AUTH: login_env and password_env set to null."""
    fake_cls = _make_fake_smtp()
    config = EmailConfig(
        host="relay.internal",
        sender="harness@example.com",
        recipients=("approver@example.com",),
        login_env=None,
        password_env=None,
    )
    channel = EmailChannel(config, transport=fake_cls)
    await channel.notify(
        _email_request(),
        hw.Envelope.new(tenant="t", principal="p"),
    )
    assert _last_fake is not None
    assert _last_fake.login_user is None


async def test_the_email_channel_raises_on_missing_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing SMTP credentials are a ProviderError, not a KeyError."""
    monkeypatch.delenv("HARNESSWEAVER_EMAIL_LOGIN", raising=False)
    monkeypatch.delenv("HARNESSWEAVER_EMAIL_PASSWORD", raising=False)
    config = EmailConfig(
        host="smtp.example.com",
        sender="h@example.com",
        recipients=("a@example.com",),
    )
    channel = EmailChannel(config, transport=_make_fake_smtp())
    with pytest.raises(hw.errors.ProviderError, match="environment variable"):
        await channel.notify(
            _email_request(),
            hw.Envelope.new(tenant="t", principal="p"),
        )


async def test_the_email_channel_wraps_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ConnectionRefusedError becomes a ProviderError (C5)."""
    _email_env(monkeypatch)
    config = EmailConfig(
        host="down.example.com",
        sender="h@example.com",
        recipients=("a@example.com",),
    )
    channel = EmailChannel(config, transport=_make_fake_smtp(fail_connect=True))
    with pytest.raises(hw.errors.ProviderError, match="email send failed"):
        await channel.notify(
            _email_request(),
            hw.Envelope.new(tenant="t", principal="p"),
        )


async def test_the_email_channel_wraps_smtp_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An SMTP protocol error becomes a ProviderError (C5, R13)."""
    _email_env(monkeypatch)
    config = EmailConfig(
        host="smtp.example.com",
        sender="h@example.com",
        recipients=("a@example.com",),
    )
    channel = EmailChannel(config, transport=_make_fake_smtp(fail_send=True))
    with pytest.raises(hw.errors.ProviderError, match="email send failed"):
        await channel.notify(
            _email_request(),
            hw.Envelope.new(tenant="t", principal="p"),
        )


async def test_the_email_channel_reports_refused_recipients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partially refused recipients raise ProviderError (R13)."""
    _email_env(monkeypatch)
    refused = {"bad@example.com": (550, b"No such user")}
    config = EmailConfig(
        host="smtp.example.com",
        sender="h@example.com",
        recipients=("ok@example.com", "bad@example.com"),
    )
    channel = EmailChannel(config, transport=_make_fake_smtp(refused=refused))
    with pytest.raises(hw.errors.ProviderError, match="1 recipient"):
        await channel.notify(
            _email_request(),
            hw.Envelope.new(tenant="t", principal="p"),
        )


async def test_the_email_message_sanitises_multiline_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reason with line breaks doesn't crash the Subject header."""
    _email_env(monkeypatch)
    request = _email_request().model_copy(update={"reason": "line one\nline two\rline three"})
    fake_cls = _make_fake_smtp()
    config = EmailConfig(
        host="smtp.example.com",
        sender="h@example.com",
        recipients=("a@example.com",),
    )
    channel = EmailChannel(config, transport=fake_cls)
    await channel.notify(request, hw.Envelope.new(tenant="t", principal="p"))
    assert _last_fake is not None
    assert "\n" not in (_last_fake.sent[0]["Subject"] or "")


async def test_the_email_config_validates_bounds() -> None:
    """Empty recipients and out-of-range ports fail at load time (R10)."""
    with pytest.raises(ValueError, match="at least"):
        EmailConfig(
            host="smtp.example.com",
            sender="h@example.com",
            recipients=(),
        )
    with pytest.raises(ValueError, match="less than or equal"):
        EmailConfig(
            host="smtp.example.com",
            sender="h@example.com",
            recipients=("a@example.com",),
            port=70000,
        )


@pytest.mark.parametrize(
    "approvals",
    [
        {"use": "webhook", "url": "https://approvals.example.com/hook"},
        {
            "use": "email",
            "host": "smtp.example.com",
            "sender": "harness@example.com",
            "recipients": ["approver@example.com"],
        },
    ],
    ids=["webhook", "email"],
)
async def test_a_failing_channel_is_traced_and_the_run_keeps_waiting(
    build: Builder,
    tmp_path: Path,
    testkit: Any,
    approvals: dict[str, Any],
) -> None:
    """Both webhook and email refuse the network in test mode (R14), so
    notifying fails; the run keeps waiting with an ``approval_notify_failed``
    trace that persists."""
    harness = build(_spec(tmp_path, approvals), tools=None)
    result = await harness.run("t", "go")
    assert result.status is hw.RunStatus.AWAITING_APPROVAL
    notes = [e for e in result.trace if e.code == "approval_notify_failed"]
    assert len(notes) == 1
    assert "ProviderError" in (notes[0].reason or "")
    stored = await harness.result(result.run_id)
    assert any(e.code == "approval_notify_failed" for e in stored.trace)
