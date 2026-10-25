# ADR-0012: No built-in price table

**Status:** Accepted

## Decision

No built-in price table. Cost comes from the provider report, then spec `models.prices`, then `genai-prices` if installed, otherwise "unknown".

## Why

Hard-coded prices go stale and mislead; one owner for pricing.
