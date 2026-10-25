# Adoption levels

HarnessWeaver is adopted level by level. Each level is useful on its own, adds a little to the spec, and builds on the one before. The harness computes the level a spec reaches, and an org baseline can require a minimum level by risk tier.

| Level | You add | You get |
| --- | --- | --- |
| **L0 Observe** | `harness.instrument(client)` | Traces, token use and cost per tenant and task, the error taxonomy |
| **L1 Guard** | `guardrails:` and typed task outputs | PII redaction, injection and secrets checks, schema validation with bounded repair |
| **L2 Govern** | tool manifests, `budgets:`, `policy:` | Tool allow-lists, argument validation, risk-based approval, budgets, an audit trail |
| **L3 Orchestrate** | `tasks:` with runners, `routing:` | Idempotency, deadlines, durable suspend and resume, routing cascades |
| **L4 Improve** | `evals:` | CI quality gates, shadow-guard reports, online sampling |

## How the level is computed

Levels are cumulative: a spec reaches L2 only if it meets every L1 and L2 requirement. Each requirement has a stable code (fixtures suite `levels`, the same in Python and TypeScript):

| Level | Code | Requirement |
| --- | --- | --- |
| L0 Observe | - | Always met: observability is always on |
| L1 Guard | `L1.enforcing_guardrail` | At least one enabled guardrail with `mode: enforce` |
| L1 Guard | `L1.task_outputs` | Every task declares an `output` (`str` for plain text) |
| L2 Govern | `L2.require_manifest` | `tools.require_manifest` is true |
| L2 Govern | `L2.run_budget` | `budgets.per_run` sets at least one limit |
| L2 Govern | `L2.policy_rules` | `policy.rules` has at least one rule |
| L3 Orchestrate | `L3.tasks` | At least one task is defined |
| L4 Improve | `L4.task_evals` | Every task has at least one eval suite |

`harnessweaver spec validate` prints the level; `harnessweaver doctor` also says what the next level needs:

```text
OK    level          adoption level L1; risk tier 'internal' requires L0
OK    next level     to reach L2: policy.rules has at least one rule
```

## Requiring a level

An org baseline picks the required level from the app's `metadata.risk_tier`:

```yaml
# acme-baseline.yaml (a profile)
require_level:
  default: L1
  tiers: { customer_facing: L2, takes_actions: L3 }
```

```yaml
# harness.yaml
metadata: { name: support-assistant, owner: cx-team, risk_tier: customer_facing }
extends: ["org://acme-baseline@^1"]
```

A spec below its required level fails to load with `LevelTooLow`, which lists the missing requirement codes. `risk_tier` defaults to `internal`; the tier names are the org's own.

## Moving up, level by level

### L0 Observe

Keep your code; govern the client it already uses.

```yaml
apiVersion: harnessweaver/v1
kind: Harness
metadata: { name: triage, owner: support-platform }
budgets:
  per_run: { max_usd: 0.05 }        # each instrumented call is one run
```

```python
harness = hw.load("harness.yaml")
client = harness.instrument(AsyncOpenAI(base_url=GATEWAY))
```

Every call is a traced run with usage and cost. To export the traces, configure OpenTelemetry in the app, or set `observability.configure_sdk: true` with `harnessweaver-otel` ([Observability](../tutorial/observability.md)).

### L1 Guard

Add guards, usually through a profile, and type your outputs.

```yaml
extends: ["profile://extraction"]   # PII redaction on input, secrets check on output, one repair
guardrails:
  input:
    - { id: injection, use: injection.heuristic, mode: log_only }   # new guards start in shadow mode
tasks:
  extract: { runner: direct, output: app.models:TicketSummary, prompt: extract@1 }
```

Use `harnessweaver add guard <provider>` to add guards in shadow mode, and promote them to `enforce` when the eval report backs them (RULES R8).

### L2 Govern

Give every tool a manifest, budget the run, and write policy rules.

```yaml
tools:
  manifests: ["tools/*.tool.yaml"]
  require_manifest: true
budgets:
  per_run: { max_usd: 1.00, max_tool_calls: 20, deadline: 2m }
policy:
  rules:
    - { id: refund-cap, when: "tool.name == 'refund_payment' && args.amount_usd > 1000", effect: deny }
```

`harnessweaver add tool app.tools:refund_payment` writes a manifest from the function; `harnessweaver tools pin` pins its digest. See [Tools](../tutorial/tools.md) and [Policy](../tutorial/policy.md).

### L3 Orchestrate

Define tasks and let a runner own them; add routing where a choice is needed.

```yaml
tasks:
  refund:
    runner: { use: pydantic_ai.agent, agent: "app.agents:refund_agent" }
    tools: [lookup_order, refund_payment]
    budget: { max_usd: 0.50, deadline: 1m }
routing:
  intent:
    options: [refund, question]
    cascade: [{ use: lexical, utterances: { refund: [i want my money back] }, threshold: 0.4 }]
    default: question
```

Runs now get idempotency keys, approvals that suspend and resume, and checkpoints ([Approvals](../tutorial/approvals.md)).

### L4 Improve

Give every task an eval suite, run it in CI, and sample production.

```yaml
evals:
  refund: [evals/golden.yaml, evals/redteam.yaml]
  online: { sample_rate: 0.05, graders: [{ status: completed }] }
```

`harnessweaver eval run` fails CI when a suite misses its threshold or a passing case regresses ([Evals](../tutorial/evals.md)).

The examples climb the same ladder: [Example 01](../resources/examples.md#example-01-invoice-extraction) is L1, Examples 02 and 03 are L4.
