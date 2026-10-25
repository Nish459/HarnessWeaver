# ADR-0019: One models section

**Status:** Accepted

## Decision

One `models` section (`provider`, `default`, `aliases`, `allowed_aliases`, `prices`) replaces the guide's separate `model_access` and `models`. Provider settings sit next to `use:` and are validated by the provider. `evals.online` is a reserved key beside the per-task suite lists.

## Why

One place to read model access; the guide's inline provider settings stay valid; the guide's `evals: {task: [files]}` form stays valid.
