"""Approval channels tell approvers a run waits; a failing one is traced (DESIGNS No. 18)."""

import json
from collections.abc import Mapping
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.modules.approvals import EmailChannel, EmailConfig, WebhookChannel, WebhookConfig

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


async def test_a_failing_channel_is_traced_and_the_run_keeps_waiting(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    # The webhook refuses the network in test mode (R14), so notifying fails.
    harness = build(
        _spec(tmp_path, {"use": "webhook", "url": "https://approvals.example.com/hook"}), tools=None
    )
    result = await harness.run("t", "go")
    assert result.status is hw.RunStatus.AWAITING_APPROVAL
    notes = [e for e in result.trace if e.code == "approval_notify_failed"]
    assert len(notes) == 1
    assert "ProviderError" in (notes[0].reason or "")
    stored = await harness.result(result.run_id)
    assert any(e.code == "approval_notify_failed" for e in stored.trace)


# -- email channel ----------------------------------------------------------


class _FakeSmtp:
    """Captures the EmailMessage instead of connecting to an SMTP server."""

    def __init__(self, *, fail: bool = False) -> None:
        self.messages: list[EmailMessage] = []
        self.fail = fail

    def __call__(
        self,
        msg: EmailMessage,
        host: str,
        port: int,
        starttls: bool,
        login: str,
        password: str,
    ) -> None:
        if self.fail:
            import smtplib

            raise smtplib.SMTPException("connection refused")
        self.messages.append(msg)
        self.host = host
        self.port = port
        self.starttls = starttls
        self.login = login
        self.password = password


def _email_request() -> hw.ApprovalRequest:
    return hw.ApprovalRequest(
        approval_id="apr_mail_1",
        run_id="run_mail_1",
        reason="refunds over $100 need finance",
        approver_role="finance",
        tool=hw.ToolInfo(name="refund_payment"),
        requested_at=hw.FakeClock().now(),
    )


async def test_the_email_channel_sends_a_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The channel builds a plain-text e-mail and hands it to the sender (C3)."""
    monkeypatch.delenv("HARNESSWEAVER_TEST_MODE", raising=False)
    monkeypatch.setenv("HARNESSWEAVER_EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("HARNESSWEAVER_EMAIL_LOGIN", "bot@example.com")
    monkeypatch.setenv("HARNESSWEAVER_EMAIL_PASSWORD", "sk-test-secret")
    fake = _FakeSmtp()
    config = EmailConfig(
        sender="harness@example.com",
        recipients=["approver@example.com", "lead@example.com"],
    )
    channel = EmailChannel(config, sender=fake)
    request = _email_request()
    await channel.notify(request, hw.Envelope.new(tenant="t", principal="p"))
    assert len(fake.messages) == 1
    msg = fake.messages[0]
    assert msg["To"] == "approver@example.com, lead@example.com"
    assert msg["From"] == "harness@example.com"
    assert "apr_mail_1" in msg["Subject"] or "refunds over" in msg["Subject"]
    body = msg.get_content()
    assert "apr_mail_1" in body
    assert "run_mail_1" in body
    assert "refund_payment" in body
    assert "harness.approve" in body
    assert fake.host == "smtp.example.com"
    assert fake.login == "bot@example.com"
    assert fake.password == "sk-test-secret"


async def test_the_email_channel_raises_on_missing_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing SMTP credentials are a ProviderError, not an unhandled KeyError."""
    monkeypatch.delenv("HARNESSWEAVER_TEST_MODE", raising=False)
    monkeypatch.delenv("HARNESSWEAVER_EMAIL_HOST", raising=False)
    monkeypatch.delenv("HARNESSWEAVER_EMAIL_LOGIN", raising=False)
    monkeypatch.delenv("HARNESSWEAVER_EMAIL_PASSWORD", raising=False)
    config = EmailConfig(sender="h@example.com", recipients=["a@example.com"])
    channel = EmailChannel(config, sender=_FakeSmtp())
    with pytest.raises(hw.errors.ProviderError, match="environment variable"):
        await channel.notify(_email_request(), hw.Envelope.new(tenant="t", principal="p"))


async def test_the_email_channel_refuses_the_network_in_test_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Like the webhook, the email channel honours R14."""
    monkeypatch.setenv("HARNESSWEAVER_TEST_MODE", "1")
    monkeypatch.setenv("HARNESSWEAVER_EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("HARNESSWEAVER_EMAIL_LOGIN", "bot@example.com")
    monkeypatch.setenv("HARNESSWEAVER_EMAIL_PASSWORD", "secret")
    config = EmailConfig(sender="h@example.com", recipients=["a@example.com"])
    channel = EmailChannel(config, sender=_FakeSmtp())
    with pytest.raises(hw.errors.ProviderError, match="test mode"):
        await channel.notify(_email_request(), hw.Envelope.new(tenant="t", principal="p"))


async def test_the_email_channel_wraps_smtp_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An SMTP failure becomes a ProviderError so the harness traces it (R13)."""
    monkeypatch.delenv("HARNESSWEAVER_TEST_MODE", raising=False)
    monkeypatch.setenv("HARNESSWEAVER_EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("HARNESSWEAVER_EMAIL_LOGIN", "bot@example.com")
    monkeypatch.setenv("HARNESSWEAVER_EMAIL_PASSWORD", "secret")
    config = EmailConfig(sender="h@example.com", recipients=["a@example.com"])
    channel = EmailChannel(config, sender=_FakeSmtp(fail=True))
    with pytest.raises(hw.errors.ProviderError, match="email send failed"):
        await channel.notify(_email_request(), hw.Envelope.new(tenant="t", principal="p"))


async def test_the_email_channel_is_traced_when_it_fails_in_a_run(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    """Like the webhook test: the email channel refuses the network in test mode (R14),
    so notifying fails, and the run keeps waiting with an ``approval_notify_failed`` trace."""
    harness = build(
        _spec(
            tmp_path,
            {
                "use": "email",
                "sender": "harness@example.com",
                "recipients": ["approver@example.com"],
            },
        ),
        tools=None,
    )
    result = await harness.run("t", "go")
    assert result.status is hw.RunStatus.AWAITING_APPROVAL
    notes = [e for e in result.trace if e.code == "approval_notify_failed"]
    assert len(notes) == 1
    assert "ProviderError" in (notes[0].reason or "")
