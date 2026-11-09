# Tool manifests

No tool runs without a manifest (RULES S2). A manifest is the contract between the tool's owner, the security team and the governor: what the model is told the tool does, how it is reached, what it may touch, and when a human must approve a call. `tools.manifests` in the spec names the files (globs relative to `harness.yaml`), and every manifest is checked when the harness loads.

```yaml
apiVersion: harnessweaver/v1
kind: Tool
metadata: { name: refund_payment, version: 2.1.0, owner: payments-team }
spec:
  transport: native
  handler: "app.tools:refund_payment"
  description: Refund part or all of a payment.
  input_schema:
    type: object
    properties:
      order_id: { type: string, pattern: "^A-[0-9]{4}$" }
      amount_usd: { type: number, minimum: 0 }
    required: [order_id, amount_usd]
  definition_digest: "sha256:9f3c..."     # pins {name, description, input_schema}
  side_effect: write_external
  risk: high
  data_access: ["pii:customer"]
  egress: [payments.internal]
  scopes: ["payments:refund"]
  tenants: []                             # enabled for these tenants; empty is all
  rate_limit: { per_principal: 10/m, per_tenant: 200/h }
  approval: { when: "args.amount_usd > 100", approver_role: finance }
  output: { max_bytes: 20000, sanitize: [pii_redact, strip_instructions], label: untrusted }
  timeout: 30s
```

## metadata

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | string | required | The tool's name, as the model and the spec see it. Letters, digits, `_`, `.` and `-`, not starting with a digit |
| `version` | string | none | The tool's version |
| `owner` | string | none | The owning team |

## spec

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `transport` | `native`, `http`, `code`, `mcp` | `native` | How the tool is reached (below) |
| `description` | string | `""` | What the model is told the tool does |
| `input_schema` | JSON Schema | `{type: object}` | The arguments, checked at governor step 2. The subset in [Schema validation](../advanced/governor.md#schema-validation) |
| `definition_digest` | `sha256:<hex>` | none | Pins `{name, description, input_schema}`; a mismatch blocks every call (rug-pull defense) |
| `handler` | import path | none | `native`: the function to call; required in a manifest file |
| `url` | URL | none | `http`: where the arguments are POSTed; required for `http` |
| `headers_env` | map | `{}` | `http`: header name to the environment variable holding its value (S1) |
| `server` | string | none | `mcp`: the MCP server that serves the tool, such as `mcp://payments`; required for `mcp`, and only `mcp` tools name one |
| `sandbox` | name | `none` | `code`: the `Sandbox` provider; `monty` is short for `monty.sandbox`. Required for `code`, and only `code` tools name one (S4) |
| `code_arg` | string | `code` | `code`: the argument that holds the code |
| `limits` | `{timeout, max_memory_mb, max_output_bytes}` | `5s`, `64`, `100000` | `code`: limits for the sandboxed code |
| `timeout` | duration | `30s` | How long a call may take |
| `side_effect` | `none`, `read`, `write_internal`, `write_external`, `destructive` | `none` | What a call changes |
| `risk` | `low`, `medium`, `high`, `critical` | `low` | How much harm a misused call does; `tools.approval_by_risk` can require approval by risk |
| `data_access` | list | `[]` | Data the tool reads. `pii:*` entries mark the run private when it runs (S3) |
| `egress` | list of hosts | `[]` | Where it can send data. A tool with egress is checked by the trifecta rule |
| `scopes` | list | `[]` | Permissions the tool needs, for policy rules and gateways |
| `tenants` | list | `[]` (all) | The tenants it is enabled for |
| `enabled` | boolean | `true` | `false` blocks every call |
| `rate_limit` | `{per_principal, per_tenant}` | none | Calls allowed, as `<count>/<s, m, h or d>` (`10/m`, `200/h`) |
| `approval` | `{when, approver_role}` | none | `when` is a cel-lite expression over the policy names (`principal`, `tenant`, `task`, `tool`, `args`, `labels`); true, or unevaluable, means a human must approve |
| `output` | output policy | below | What the governor does to the result before anything else sees it |

`output`:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `max_bytes` | integer > 0 | `tools.max_output_bytes` | Cut the result to this many UTF-8 bytes (a JSON result becomes its compact JSON text first) |
| `sanitize` | list of `pii_redact`, `strip_instructions` | `[]` | Sanitizers, run in that order on values and object keys. Keys that sanitize to one name stay distinct (`[EMAIL]`, `[EMAIL]#2`) |
| `label` | `untrusted` or `trusted` | `untrusted` | Whether the result marks the run as having seen untrusted content |

## Transports

| Transport | Calls | Notes |
| --- | --- | --- |
| `native` | `handler`, imported when the harness loads, sync or async, with the arguments as keyword arguments | A handler that takes an `idempotency_key` argument receives the call's key |
| `http` | POSTs the arguments as JSON to `url` | Headers from `headers_env`; an `Idempotency-Key` header; refuses to call out in test mode (R14) |
| `code` | Runs the code in `code_arg` in the named `Sandbox`, with the other arguments as globals, never in the host process | Needs a sandbox plugin such as `harnessweaver-monty` |
| `mcp` | *Planned* | The harness refuses to load an `mcp` tool for now; `harnessweaver gateway mcp` already lists it for an MCP gateway |

## Digests

`definition_digest` is `sha256:` followed by the hex SHA-256 of the canonical JSON of `{name, description, input_schema}`: keys sorted, no spaces, non-ASCII characters escaped, integral numbers written as integers (fixtures suite `governor`, so Python and TypeScript agree).

- A manifest whose pin doesn't match its definition still loads, and **every call to it is blocked** with `digest_mismatch`, so a tool changed without review can't run.
- `harnessweaver doctor` fails a mismatched pin and warns about unpinned manifests, printing the digest to pin.
- `harnessweaver tools pin` writes each manifest's current digest into it, keeping comments; `--tool NAME` pins one.
- `hw.definition_digest(name, description, input_schema)` computes it in code.

## Writing a manifest

`harnessweaver add tool app.tools:refund_payment --risk high --side-effect write_external` writes a manifest from the function: the name is the function's, the description its docstring summary, and the input schema comes from its parameters. It adds the directory to `tools.manifests`. Review the result, fill in `egress`, `data_access`, `approval` and `rate_limit`, then pin it. The [Spec generator](../learn/spec-generator.md) (*Tool manifest*) writes one from choices in a form instead.

## Tools given in code

A tool registered in code (a test's `FakeTool`, or an adapter's own tools) carries a manifest too, built with `ToolDescription.from_manifest(...)`, so `tools.require_manifest` covers it. In TypeScript, give the handlers to `load("harness.yaml", { tools: { refund_payment } })`; each still needs its manifest file.

See [Tools](../tutorial/tools.md) for the nine-step governor that enforces all of this.
