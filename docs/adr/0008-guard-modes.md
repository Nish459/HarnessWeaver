# ADR-0008: Spec guards enforce by default; the CLI scaffolds shadow guards

**Status:** Accepted

## Decision

Guards declared in a spec default to `mode: enforce` (so the guide's baseline examples enforce as written). The CLI scaffolds new guards with `mode: log_only`, and `doctor` lists shadow guards.

## Why

Keeps baseline semantics obvious while making shadow-first the path of least resistance (R8).
