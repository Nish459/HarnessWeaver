"""The help desk's tools."""

REFUNDS: list[float] = []
"""Every refund made, so tests can see a call ran exactly once."""


def refund_payment(amount_usd: float) -> dict[str, float]:
    """Refund ``amount_usd`` and say so."""
    REFUNDS.append(amount_usd)
    return {"refunded": amount_usd}
