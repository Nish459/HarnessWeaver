"""The support desk's tools. Their manifests are in tools/*.tool.yaml."""

ORDERS = {
    "A-1001": {"order_id": "A-1001", "status": "delivered", "total_usd": 250.0},
    "A-1002": {"order_id": "A-1002", "status": "shipped", "total_usd": 40.0},
}


async def lookup_order(order_id: str) -> dict[str, object]:
    """Look up an order's status and total by its id."""
    return ORDERS.get(order_id, {"order_id": order_id, "status": "unknown"})
