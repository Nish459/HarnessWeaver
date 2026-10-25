# ADR-0007: The sidecar speaks HTTP/JSON first

**Status:** Accepted

## Decision

Sidecar speaks HTTP/JSON (FastAPI, OpenAPI) first; gRPC from the proto later.

## Why

Fastest path for every language; the proto keeps the gRPC option open.
