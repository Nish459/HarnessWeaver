"""The ``approvals`` module: telling approvers a run waits for them (DESIGNS No. 18).

A suspended run's request is saved with its checkpoint first; then the channel
``approvals.use`` names is notified. Answers come back through
``harness.approve(...)``, which checks the approver's role, re-checks edited
arguments and resumes the run.
"""

from harnessweaver.modules.approvals.channels import (
    CallbackChannel,
    CallbackConfig,
    ConsoleChannel,
    ConsoleConfig,
    EmailChannel,
    EmailConfig,
    MemoryChannel,
    SmtpTransport,
    WebhookChannel,
    WebhookConfig,
)

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
