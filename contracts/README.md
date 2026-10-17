# Contracts

The contracts are the source of truth that every HarnessWeaver implementation (Python, TypeScript and the `harnessd` sidecar) is tested against (RULES R11, DESIGNS No. 24).

```
contracts/
|-- schemas/                 JSON Schemas (draft 2020-12) of every wire contract
`-- fixtures/conformance/    language-neutral behavior fixtures, one folder per suite
```

## Schemas

The schemas are generated from the Pydantic models in `python/harnessweaver` (ADR-0005) and checked in so reviewers and other languages read the contract directly. A test fails if a checked-in schema drifts from its model.

```bash
make schemas          # regenerate after changing a contract model
make schemas-check    # report drift
```

| Schema | Contract |
| --- | --- |
| `harness`, `profile` | The `harness.yaml` app spec and profile documents (complete documents; profiles and overlays may be partial) |
| `envelope` | The immutable run context every hook event carries |
| `hook-event` | The 13 hook event payloads, discriminated by `hook` |
| `outcome` | What middleware returns: `continue`, `retry`, `escalate`, `suspend`, `block` |
| `decision-request`, `decision` | Routing questions and answers |
| `guard-result` | A guardrail's verdict and its seven actions |
| `model-request`, `model-response`, `tool-call` | Neutral model-call contracts (R7) |
| `tool-info`, `tool-result` | Tool facts policies decide on, and tool output |
| `context-item` | A retrieved item with its ACL |
| `approval-request`, `approval-decision` | Human-in-the-loop approvals |
| `error-info` | The serializable error taxonomy |

Every schema has `$id` `urn:harnessweaver:v1:<name>`. Within `harnessweaver/v1`, changes are additive only (V2).

## Conformance fixtures

Each suite folder holds one or more JSON files of this shape:

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

The fields of a case depend on the suite:

| Suite | Case fields | Expectation |
| --- | --- | --- |
| `durations` | `input` (string or number of seconds) | `{ms, canonical}` or `{error: true}` |
| `semver` | `version`, `compare: [a, b]`, or `range` | canonical text, `-1/0/1`, `{matches, rejects}`, or `{error: true}` |
| `outcomes` | `outcome` or `outcomes: [...]` | `{severity}` or `{kind, index}` (first most severe; `null` when empty) |
| `hook_order` | `directions` map, or `hook` + `middleware: [{name, band}]` | execution order of names |
| `expr` | `expr`, optional `vars` | `{value, type?}` or `{error: "syntax" \| "eval"}` |
| `merge` | `layers: [{name, kind, data}]`, or a run budget (`per_run`, `task_budget`, `overrides`, optional `bounds`) | merged `value` plus `provenance` (path to layer name), the `budget`, or `{error, lock?, bound?}` with `error` one of `lock_violation`, `bound_violation`, `spec_invalid` |
| `levels` | `spec` sections and `risk_tier` | `{level, required, unmet}` with requirement codes by level |

Expected values are written by hand from the design, never copied from an implementation's output. When `expect.type` is given for a number, implementations must also return that cel-lite type (`int` or `double`).

A new suite needs a runner in every language. The Python runners live in `python/harnessweaver/tests/conformance/`, and that directory's tests fail if a suite folder has no runner.
