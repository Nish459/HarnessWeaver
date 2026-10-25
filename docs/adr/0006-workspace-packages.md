# ADR-0006: One uv workspace of separate packages

**Status:** Accepted

## Decision

uv workspace with separate core, CLI, sidecar and first-party plugin packages; plugins are exposed as core extras for convenience.

## Why

Keeps the core small (R6) and lets each plugin version on its own.
