# ADR-0010: The core uses only the OpenTelemetry API

**Status:** Accepted

## Decision

The core uses only the OTel API plus an always-on in-memory `RunTrace`. SDK and exporter setup lives in the `otel.sdk` provider of `harnessweaver-otel`.

## Why

One owner for telemetry setup (R5); testable traces without an SDK.
