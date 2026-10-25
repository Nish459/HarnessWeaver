# ADR-0029: Routing cascades and shared text scoring

**Status:** Accepted

## Decision

A router is a cascade: stages run in order, the first confident answer wins (exact always; probabilistic at or above the stage's threshold, any confidence without one), answers outside the options and failing stages abstain, and the router's `default` answers when no stage is confident. Every stage's answer is traced. The built-in `lexical` and `semantic` stages and the `memory` context provider share one text scoring: letter-and-digit tokens, cosine of token counts, and a hashing embedder (FNV-1a over words and trigrams).

## Why

The guide's cascade, made exact so Python, TypeScript and the sidecar route identically (fixtures suite `routing`); a dependency-free embedder keeps semantic routing in the core (R6) while `encoder:` lets a plugin bring real embeddings.
