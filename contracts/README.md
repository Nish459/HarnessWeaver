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
| `tool-manifest`, `tool-verdict` | A `kind: Tool` manifest (S2), and the governor's decision about one call |
| `policy-request`, `policy-decision` | What a `PolicyEngine` is asked and answers |
| `sandbox-result` | What a `Sandbox` returns for code it ran |
| `context-item` | A retrieved item with its ACL |
| `approval-request`, `approval-decision` | Human-in-the-loop approvals |
| `trace-event` | One entry in a run's trace: a hook that fired, a middleware's outcome or failure, or a framework note |
| `run-result`, `run-event` | A run's status, output or error, usage, cost and trace; and the progress events `harness.stream` yields |
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
| `bus` | `hook`, a starting `value`, and `middleware: [{name, band, fail_mode, does}]` | the combined `outcome`, the middleware that `ran`, what each one `saw`, the final `value` and the per-middleware `trace`, or `{error}` |
| `budgets` | `limits` and `ops` (`model.before`, `model.after`, `tool.before`), or a `cost` lookup | the limit each op breached, the `meter` afterwards and what is `remaining`; or the cost's `usd` and `source` |
| `plugins` | `owner_of`, `qualify`, `owns`, `allowed` or `namespace` | the owning namespace, the qualified name, or `true`/`false` |
| `guards` | `guard` + `config` + `content`, or a pipeline: `stage`, `guards: [{id, use, config, action, mode, parallel}]`, `content` | the provider's `{action, content, findings, score}`, or the combined `outcome`, the payload's `content` afterwards and a trace `note` |
| `governor` | a `definition`; a `rate`; a `schema` and `value`; `rules`, `default_effect` and a policy `request`; a `tool` (manifest fields) with `args` and the run's `principal`, `tenant`, `task`, `labels`, `policy`, `tools`, `task_approvals`, `previous_calls`, `approved`; or an `output` with an output `policy` | the `canonical` text and `digest`; `{count, seconds}`; `{valid, locations}` or `{error}`; the `{effect, rule}`; the `{decision, step, code}`; or the sanitized `{output, truncated, untrusted}` |

Expected values are written by hand from the design, never copied from an implementation's output. When `expect.type` is given for a number, implementations must also return that cel-lite type (`int` or `double`).

A new suite needs a runner in every language. The Python runners live in `python/harnessweaver/tests/conformance/`, and that directory's tests fail if a suite folder has no runner.
