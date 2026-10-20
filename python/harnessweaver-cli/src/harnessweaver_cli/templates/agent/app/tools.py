"""The tools the agent may call. Their manifests in tools/ govern every call."""

from typing import Any

ORDERS: dict[str, dict[str, Any]] = {
    "A-1001": {"status": "shipped", "total_usd": 120.0},
    "A-1002": {"status": "delivered", "total_usd": 900.0},
}
REFUNDS: list[dict[str, Any]] = []
"""Refunds issued, kept in memory for the demo and the tests."""


def lookup_order(order_id: str) -> dict[str, Any]:
    """Look up an order by its id."""
    order = ORDERS.get(order_id)
    return {"order_id": order_id, **order} if order else {"order_id": order_id, "found": False}


def refund_payment(order_id: str, amount_usd: float, idempotency_key: str) -> dict[str, Any]:
    """Refund part or all of an order's payment.

    The governor passes ``idempotency_key``; a payment API should be given it, so a
    retried or resumed call never refunds twice.
    """
    if any(r["key"] == idempotency_key for r in REFUNDS):
        return {"order_id": order_id, "refunded_usd": amount_usd, "duplicate": True}
    REFUNDS.append({"order_id": order_id, "amount_usd": amount_usd, "key": idempotency_key})
    return {"order_id": order_id, "refunded_usd": amount_usd}
