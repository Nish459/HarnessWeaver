"""Acme's own plugin, loaded through ``plugins.local``: a middleware and a guard.

Any team can extend the harness with the contract every plugin uses: one
``hw.Plugin`` that names its contributions under its namespace, here ``acme``
(DESIGNS No. 13). The org baseline lists ``acme`` in ``plugins.allow``, so apps
may load it.
"""

import re

from pydantic import BaseModel, ConfigDict

import harnessweaver as hw

__all__ = ["AccountIds", "no_weekend_refunds", "plugin"]


@hw.middleware(hooks=["tool.before"], band="app", fail_mode="closed", timeout="1s")
async def no_weekend_refunds(event: hw.ToolCallEvent, env: hw.Envelope) -> hw.Outcome | None:
    """Refunds asked for on a weekend wait for finance, whatever their amount.

    The day comes from the run's injected clock, never the wall clock (RULES C4),
    so tests can pick it. A call finance already approved passes.
    """
    if event.call.name != "refund_payment" or event.approval is not None:
        return None
    if env.clock.is_weekend():
        return hw.Suspend(reason="refunds on weekends need finance", approver_role="finance")
    return None


class AccountIdsConfig(BaseModel):
    """``use: acme.account_ids`` takes no settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)


_ACCOUNT = re.compile(r"\bACME-\d{8}\b")


@hw.provider(
    port="Guardrail",
    name="acme.account_ids",
    config=AccountIdsConfig,
    deterministic=True,
    latency_class="fast",
)
class AccountIds:
    """Redacts Acme billing account numbers (``ACME-`` and eight digits)."""

    def __init__(self, config: AccountIdsConfig | None = None) -> None:
        self.config = config or AccountIdsConfig()

    async def check(self, content: str, env: hw.Envelope) -> hw.GuardResult:
        """Replace each account number with ``[ACCOUNT]``; account numbers are private."""
        found = [
            hw.Finding(type="ACCOUNT", start=m.start(), end=m.end(), private=True)
            for m in _ACCOUNT.finditer(content)
        ]
        if not found:
            return hw.GuardResult.allow()
        redacted = _ACCOUNT.sub("[ACCOUNT]", content)
        return hw.GuardResult.redact(redacted, findings=tuple(found), reason="account numbers")


plugin = hw.Plugin(
    namespace="acme",
    version="1.0.0",
    providers=[AccountIds],
    middleware=[no_weekend_refunds],
    description="Acme's own guards and middleware.",
)
