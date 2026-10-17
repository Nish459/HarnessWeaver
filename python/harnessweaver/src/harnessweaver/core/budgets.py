"""Budget accounting and cost resolution (DESIGNS No. 10, ADR-0012, fixtures suite ``budgets``).

A :class:`BudgetMeter` counts what one run has used and says which limit a step
would breach. Checks happen at fixed points:

* ``model.before``: the call count, tokens and cost so far, and whether the
  estimated input of the next call fits in the tokens left.
* ``model.after``: the actual usage and cost are added; going over a limit blocks.
* ``tool.before``: the tool-call count.

Cost comes from the provider's report, then the spec's ``models.prices``,
otherwise it is unknown. Unknown cost is flagged, never guessed (ADR-0012).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

from harnessweaver.core.envelope import Budget
from harnessweaver.core.messages import ModelRequest, ModelResponse, Usage
from harnessweaver.core.outcomes import Block
from harnessweaver.core.state import MeterSnapshot

__all__ = [
    "BUDGET_CODE",
    "BudgetMeter",
    "CostSource",
    "PriceLookup",
    "breach_block",
    "estimate_tokens",
    "resolve_cost",
]

BUDGET_CODE = "budget_exceeded"

type PriceLookup = Callable[[str], tuple[float, float] | None]
"""``model -> (USD per million input tokens, USD per million output tokens)``."""

type CostSource = Literal["provider", "prices", "unknown"]

type Limit = Literal["max_usd", "max_tokens", "max_model_calls", "max_tool_calls"]


def estimate_tokens(request: ModelRequest) -> int:
    """A cheap estimate of a request's input tokens: one per four characters.

    Characters are Unicode code points, so every language counts the same way.
    """
    chars = sum(len(message.content) for message in request.messages)
    return math.ceil(chars / 4)


def resolve_cost(
    response: ModelResponse, request: ModelRequest, prices: PriceLookup | None
) -> tuple[float | None, CostSource]:
    """The USD cost of one call and where it came from (ADR-0012).

    Prices are looked up by the response's model, then the request's model, then
    the request's alias.
    """
    if response.cost_usd is not None:
        return response.cost_usd, "provider"
    if prices is not None:
        for model in (response.model, request.model, request.alias):
            price = prices(model) if model else None
            if price is not None:
                per_input, per_output = price
                usd = (
                    response.usage.input_tokens * per_input
                    + response.usage.output_tokens * per_output
                ) / 1_000_000
                return usd, "prices"
    return None, "unknown"


def breach_block(limit: Limit, limits: Budget) -> Block:
    """The ``Block`` a breached limit turns into."""
    return Block(reason=f"budget {limit} ({getattr(limits, limit)}) reached", code=BUDGET_CODE)


@dataclass(slots=True)
class BudgetMeter:
    """What one run has used against its limits."""

    limits: Budget
    usd: float = 0.0
    cost_known: bool = True
    usage: Usage = field(default_factory=Usage)
    model_calls: int = 0
    tool_calls: int = 0

    def check_model_call(self, request: ModelRequest) -> Limit | None:
        """The limit the next model call would breach, or ``None`` if it may go ahead."""
        limits = self.limits
        if limits.max_model_calls is not None and self.model_calls >= limits.max_model_calls:
            return "max_model_calls"
        if limits.max_tokens is not None:
            used = self.usage.total_tokens
            if used >= limits.max_tokens or used + estimate_tokens(request) > limits.max_tokens:
                return "max_tokens"
        if limits.max_usd is not None and self.usd >= limits.max_usd:
            return "max_usd"
        return None

    def start_model_call(self) -> None:
        self.model_calls += 1

    def record_model_call(self, usage: Usage, cost: float | None) -> Limit | None:
        """Add a call's usage and cost; return the limit it went over, if any."""
        self.usage = self.usage + usage
        if cost is None:
            self.cost_known = False
        else:
            self.usd += cost
        limits = self.limits
        if limits.max_tokens is not None and self.usage.total_tokens > limits.max_tokens:
            return "max_tokens"
        if limits.max_usd is not None and self.usd > limits.max_usd:
            return "max_usd"
        return None

    def check_tool_call(self) -> Limit | None:
        """The limit the next tool call would breach, or ``None``."""
        if self.limits.max_tool_calls is not None and self.tool_calls >= self.limits.max_tool_calls:
            return "max_tool_calls"
        return None

    def start_tool_call(self) -> None:
        self.tool_calls += 1

    def remaining(self, time_left: timedelta | None = None) -> Budget:
        """What is left of each limit (never negative), as a :class:`Budget`."""
        limits = self.limits

        def left[N: (int, float)](limit: N | None, used: N) -> N | None:
            return None if limit is None else max(limit - used, type(limit)(0))

        return Budget(
            max_usd=left(limits.max_usd, self.usd),
            max_tokens=left(limits.max_tokens, self.usage.total_tokens),
            max_model_calls=left(limits.max_model_calls, self.model_calls),
            max_tool_calls=left(limits.max_tool_calls, self.tool_calls),
            deadline=time_left if time_left is not None else limits.deadline,
        )

    def snapshot(self) -> MeterSnapshot:
        return MeterSnapshot(
            usd=self.usd,
            cost_known=self.cost_known,
            usage=self.usage,
            model_calls=self.model_calls,
            tool_calls=self.tool_calls,
        )

    @classmethod
    def restore(cls, limits: Budget, snapshot: MeterSnapshot) -> "BudgetMeter":
        return cls(
            limits=limits,
            usd=snapshot.usd,
            cost_known=snapshot.cost_known,
            usage=snapshot.usage,
            model_calls=snapshot.model_calls,
            tool_calls=snapshot.tool_calls,
        )
