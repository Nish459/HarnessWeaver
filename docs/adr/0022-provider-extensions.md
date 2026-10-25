# ADR-0022: Provider extensions on messages and responses

**Status:** Accepted

## Decision

`Message` and `ModelResponse` carry `extensions`: provider data keyed by namespace that the harness treats as opaque and replays unchanged with the message.

## Why

Some APIs require a model's own per-turn data back on the next request (Claude's thinking blocks must be replayed unchanged for reasoning to carry over). A neutral, JSON-only field keeps SDK types out of contracts (R7) and survives checkpoints.
