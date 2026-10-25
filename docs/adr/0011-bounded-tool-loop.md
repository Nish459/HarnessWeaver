# ADR-0011: The direct runner's bounded tool loop

**Status:** Accepted

## Decision

The `direct` runner may run a **bounded** governed tool loop (`max_steps`, no planning, no memory, no templating).

## Why

Apps need a zero-dependency way to call tools under governance. Open-ended agent behavior stays in adapters (R12).
