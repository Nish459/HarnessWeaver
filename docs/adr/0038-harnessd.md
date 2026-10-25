# ADR-0038: harnessd serves one spec over /v1

**Status:** Accepted

## Decision

`harnessd` serves one effective spec over `/v1`, loaded as an app loads it. Checks (`guards/{stage}` for `input`, `context` and `output`, `decisions/{router}`, `tools/{name}/sanitize`, `validate`) each run as a one-step session and answer with its `RunResult`; lookups, runs, approvals, the policy engine, the governor's dry run and evals answer with the harness's own contracts. Request models are contracts in `harnessweaver.core.sidecar`; the OpenAPI document is generated from them and drift-tested, and the proto mirrors its routes. Every route except `health` needs the bearer token, compared in constant time; harnessd refuses to start without one and binds 127.0.0.1. Taxonomy errors map to HTTP statuses with `ErrorInfo` bodies; invalid requests are described by location, never by value. A guard declared `where: sidecar` keeps its place on the bus and posts its provider's check to `guards/providers/{name}:check`. Tool results go through `tools/{name}/sanitize` (step 9, then `tool.after`), not a `tool_result` guard stage.

## Why

A session is already a run, so `run.start` rules, budgets, traces and stored results cover every check with no new machinery, and one answer shape keeps thin clients small; the app holding the token already decides who it acts for, as in-process code does; a remote provider behind the guard's own fail mode keeps R2; a governed call sanitizes and fires `tool.after` together, so a client can't do one without the other.
