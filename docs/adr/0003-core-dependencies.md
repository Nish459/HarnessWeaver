# ADR-0003: The core's dependencies

**Status:** Accepted

## Decision

Core dependencies are `pydantic`, `opentelemetry-api`, `pyyaml`, `anyio` (`loguru` added by ADR-0024).

## Why

The guide's two, plus the YAML parser the spec format needs and the async library the guide names. HTTP uses the stdlib via `anyio.to_thread`.
