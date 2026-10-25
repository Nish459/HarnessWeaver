# ADR-0009: Durability starts as state-store checkpoints

**Status:** Accepted

## Decision

Durability starts as `StateStore` checkpoints (memory, SQLite). Temporal and DBOS runners come later as plugins.

## Why

The guide's recommendation; no scheduler of our own.
