# ADR-0040: The TypeScript SDK

**Status:** Accepted

## Decision

The TypeScript SDK is a native port of the core, held to the shared fixtures and scoped to the Session style. `@harnessweaver/core` loads the same specs and runs what DESIGNS No. 24 lists; it never calls a model itself. `@harnessweaver/ai-sdk` governs AI SDK v7 models with a `LanguageModelV4Middleware`: each call checks the allowed aliases and budgets and fires `model.before`, whose text changes are written back into the prompt (system, user and tool-result text; never the model's own earlier answers), and `model.after`, whose text changes reach the app; a stream fires `stream.chunk` per text delta (`text_so_far` is the text before it) and closes the call on its `finish` part. The model's own errors pass through so the AI SDK's retries still work. A `Suspend` escalates. Plugins register with `definePlugin`. Schemas and built-in profiles are embedded as generated code (`scripts/sync-contracts.mjs`, drift-tested). cel-lite ints are `bigint`, canonical JSON matches Python's (float repr, code-point key order), and string positions and sizes count code points. Packages build with `tsc`, and settings and tool arguments are checked by the ADR-0026 validator subset (plus `propertyNames` and defaults). Dependencies: `yaml` (YAML 1.2 core schema, unique keys, ADR-0017) at runtime; `ai` and `@ai-sdk/provider` as peers of `@harnessweaver/ai-sdk`; `typescript`, `vitest`, `@types/node` and `zod` (the AI SDK's peer) for development.

## Why

Shared fixtures, not reading one implementation to write another, keep the cores identical (R11). In a TypeScript web app the AI SDK owns the model loop, so governing its model interface covers every call without a second provider layer, and redactions must reach the real request. Waiting for a person needs durable state, which is the sidecar's for now. Embedding the contracts keeps the package usable outside this repository. `bigint` and code-point counting are how JavaScript gives Python's answers. `tsc` and the small validator keep runtime dependencies to one package (C10), instead of tsup, zod or ajv.
