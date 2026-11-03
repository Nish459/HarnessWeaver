# Contracts

The contracts are the source of truth every HarnessWeaver implementation is tested against: the Python core, the TypeScript core and the harnessd sidecar (RULES R11). They live in [`contracts/`](https://github.com/Wise-DreamerZ/HarnessWeaver/tree/main/contracts), versioned as `harnessweaver/v1`. Read them when you build a client in another language, an integration, or a plugin that crosses process boundaries.

```text
contracts/
  schemas/                  JSON Schemas (draft 2020-12) of every wire contract
  openapi/                  harnessd's HTTP/JSON API, generated and drift-tested
  proto/harnessweaver/v1/   harnessd's services, mirroring the OpenAPI routes for gRPC later
  fixtures/conformance/     language-neutral behavior fixtures, one folder per suite
```

## Schemas

The schemas are generated from the Pydantic contract models in the Python core and checked in, so reviewers and other languages read the contract directly. A test fails if a checked-in schema drifts from its model. Every schema has the `$id` `urn:harnessweaver:v1:<name>`.

| Schema | Contract |
| --- | --- |
| `harness`, `profile` | The `harness.yaml` app spec and profile documents (complete documents; profiles and overlays may be partial) |
| `envelope` | The immutable run context every hook event carries |
| `hook-event` | The 13 hook event payloads, discriminated by `hook` |
| `outcome` | What middleware returns: `continue`, `retry`, `escalate`, `suspend`, `block` |
| `decision-request`, `decision` | Routing questions and answers |
| `guard-result` | A guardrail's verdict and its seven actions |
| `model-request`, `model-response`, `tool-call` | The neutral model-call contracts (R7) |
| `tool-info`, `tool-result` | Tool facts policies decide on, and tool output |
| `tool-manifest`, `tool-verdict` | A `kind: Tool` manifest, and the governor's decision about one call |
| `policy-request`, `policy-decision` | What a `PolicyEngine` is asked and answers |
| `sandbox-result` | What a `Sandbox` returns for code it ran |
| `context-item` | A retrieved item with its ACL |
| `approval-request`, `approval-decision` | Human-in-the-loop approvals |
| `trace-event` | One entry in a run's trace |
| `run-result`, `run-event` | A run's status, output or error, usage, cost and trace; and the progress events `harness.stream` yields |
| `error-info` | The serializable error taxonomy |
| `eval-dataset`, `eval-sample`, `grade`, `suite-result`, `baseline`, `online-sample` | Eval datasets, what a grader sees and says, a suite's results, its stored baseline, and a graded production sample |
| `policy-tests` | A `harnessweaver policy test` table |
| `recorded-call`, `replay-report` | What a recorded run got from outside, and what replaying it found |
| `tool-allow-list` | The tools a gateway may let through, and the ones only the harness may run |

```bash
make schemas          # regenerate after changing a contract model (also the OpenAPI document)
make schemas-check    # report drift
uv run harnessweaver contracts export DIR [--check]
```

## The sidecar's API

[`openapi/harnessd.openapi.json`](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/contracts/openapi/harnessd.openapi.json) describes every `/v1` route of harnessd. It is generated from the routes and the request models in `harnessweaver.core.sidecar`, so `make schemas` writes it and `make schemas-check` reports drift. `proto/harnessweaver/v1/harnessd.proto` mirrors the same routes in its `google.api.http` options for gRPC serving later; a test fails if a route is in one and not the other. Generate a client from the OpenAPI document for any language; see [harnessd](../advanced/sidecar.md).

## Conformance fixtures

Behavior that is part of the contract is pinned by JSON fixtures that every implementation must pass. Each suite folder holds files of this shape:

```json
{
  "suite": "expr",
  "description": "What this file covers.",
  "cases": [
    { "name": "unique within the file", "expr": "args.amount_usd > 100",
      "vars": { "args": { "amount_usd": 250 } }, "expect": { "value": true } }
  ]
}
```

| Suite | Pins down |
| --- | --- |
| `durations` | Duration parsing and canonical text |
| `semver` | Versions, comparisons and npm-style ranges |
| `outcomes` | Severity and combining outcomes |
| `hook_order` | Hook directions and middleware order by band |
| `bus` | Running middleware: outcomes, modifications, fail modes, timeouts, the trace |
| `expr` | cel-lite: literals, access, operators, functions, macros, logic, errors |
| `merge` | Layer merging, keyed lists, locks, bounds, provenance, per-run budgets |
| `levels` | Adoption levels and requirement codes |
| `budgets` | Budget checks at each hook, and cost resolution |
| `plugins` | Namespaces, qualified names, ownership, allow-lists |
| `guards` | The built-in guards, and the guard pipeline (actions, modes, parallel groups, approvals) |
| `governor` | Definition digests, rate limits, the schema subset, policy combination, the governor's steps, output sanitizing |
| `routing` | Tokens, lexical similarity, the hashing embedder, stages and cascades |
| `evals` | Graders, dataset validation, summaries, baselines and regressions, sampling, the shadow-guard report |

Expected values are written by hand from the design, never copied from an implementation's output. A new suite needs a runner in every language: the Python runners live in `python/harnessweaver/tests/conformance/` and the TypeScript runners in `typescript/packages/core/test/`, and both fail when a suite folder has no runner. The full case format per suite is in [contracts/README.md](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/contracts/README.md).

## Changing a contract

Within `harnessweaver/v1`, changes are additive only: new optional fields, new hook points, new actions (RULES V2). Anything else needs an ADR and a new major `apiVersion`, with the previous major supported for 12 months. A contract change starts in the model, then `make schemas`, then fixtures, and isn't released until Python, TypeScript and the sidecar all pass (R11). See [Versioning](../deployment/versions.md).
