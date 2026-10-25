# ADR-0031: A namespaced memory store, not a memory model

**Status:** Accepted

## Decision

`Memory` is a key-value port with expiry, namespaced by the harness as `(tenant, principal, task)` and exposed as `s.memory`; the built-in provider is in-process.

## Why

A namespaced store is infrastructure every app needs; what to remember stays with the app or its agent framework, so the core gains no memory model (R12).
