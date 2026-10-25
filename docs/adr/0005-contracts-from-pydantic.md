# ADR-0005: Contracts are Pydantic models; schemas are generated

**Status:** Accepted

## Decision

Contract models are Pydantic. JSON Schemas are generated, checked in under `contracts/schemas`, and drift-tested. Behavioral contracts live in JSON fixtures.

## Why

One authoring language without losing a reviewed, language-neutral contract. Revisit schema-first codegen if a third native SDK appears.
