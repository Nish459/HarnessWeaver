"""The support agent. It has no model of its own: the harness's ``models`` answer it,
and the harness offers it the task's tools (``tasks.support.tools``)."""

from pydantic_ai import Agent

support_agent: Agent[None, str] = Agent(
    name="support",
    instructions=(
        "You help customers with their orders. Look an order up before you act on it, "
        "and never refund more than the order's total."
    ),
)
