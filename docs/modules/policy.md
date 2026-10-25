# Policy

Policy decides, deterministically, whether a tool call may run (and whether a run may start at all). Rules are cel-lite expressions in the spec, compiled when it loads, and every engine combines them the same way. A policy engine must be deterministic: no classifier, judge or model ever grants anything (RULES R3).

```yaml
policy:
  use: cel_lite                 # the default; cel.policy for full CEL
  default_effect: allow         # for tool calls no rule matches
  rules:
    - { id: known-callers, hook: run.start, when: "principal.id == 'anonymous'", effect: deny }
    - { id: refund-cap, when: "tool.name == 'refund_payment' && args.amount_usd > 1000", effect: deny,
        reason: "refunds over $1000 go through the finance desk" }
    - { id: no-contractor-refunds, when: "tool.name == 'refund_payment' && 'contractor' in principal.roles", effect: deny }
    - { id: big-refunds, when: "tool.name == 'refund_payment' && args.amount_usd > 100", effect: require_approval }
    - { id: read-only-for-trials, when: "principal.attrs.plan == 'trial' && tool.side_effect != 'read'", effect: deny }
```

## Effects

| Effect | Meaning at `tool.before` | Meaning at `run.start` |
| --- | --- | --- |
| `allow` | The call may go ahead (subject to the rest of the governor) | - (a `run.start` rule only restricts) |
| `require_approval` | A human must approve the call (governor step 7) | The run escalates, because it can't wait before it starts |
| `deny` | The call is blocked, code `policy_denied` | The run is blocked, code `policy_denied` |

## How rules combine

Every `PolicyEngine` combines `policy.rules` the same way ([ADR-0025](../adr/0025-governor-placement.md); fixtures suite `governor`):

1. Take the rules for this hook (`tool.before` by default, or `run.start`) whose `when` is true.
2. `deny` beats `require_approval`, which beats `allow`. Among rules with the same effect, the first decides (its `id` and `reason` are reported).
3. A `when` that can't be evaluated **never loosens** a decision: `deny` and `require_approval` rules whose `when` fails count as matching; `allow` rules whose `when` fails don't.
4. When no rule matches a tool call, `default_effect` decides. When no `run.start` rule matches, the run starts: `default_effect` applies to tool calls only.

So a rule set reads as a list of exceptions to the default: with `default_effect: allow`, write `deny` and `require_approval` rules for what must be stopped or checked; with `default_effect: deny`, write `allow` rules for what is permitted.

## What rules can read

| Hook | Variables |
| --- | --- |
| `tool.before` | `principal` (`id`, `roles`, `attrs`), `tenant`, `task`, `tool` (`name`, `version`, `side_effect`, `risk`, `egress`, `data_access`, `scopes`), `args`, `labels` |
| `run.start` | `principal`, `tenant`, `task`, `labels` |

Names are checked when the spec loads: a `run.start` rule that reads `args` fails then (R4). See [cel-lite expressions](../spec/expressions.md).

## Where policy runs

- **Governor step 3**, for every tool call, after the `tool.before` middleware, on the final arguments ([Tools](tools.md#the-governor)). Approval can also come from the manifest's `approval.when`, `tools.approval_by_risk` and a task's `approvals.tools`; a judge at step 6 can only tighten the result.
- **`run.start`**, for `hook: run.start` rules, before any work: in `harness.run`, in sessions, and in every harnessd check.

## Engines

| Engine | From | Notes |
| --- | --- | --- |
| `cel_lite` | The core | The default; the same in Python and TypeScript |
| `cel.policy` | `harnessweaver-cel` | Full CEL through cel-python. Stricter than cel-lite: it doesn't mix ints and doubles (`1 + 0.5` is an error), and such an error makes the rule unevaluable, so `deny` and `require_approval` rules still apply |

Both pass the shared `governor` fixtures. Cedar, OPA and OpenFGA engines are *planned*; any `PolicyEngine` provider must declare `deterministic=True`, or loading fails (R3).

## Asking the engine directly

```python
decision = await harness.decide_policy(hw.PolicyRequest(
    hook="tool.before", principal=user, tenant="acme",
    tool=tool_info, args={"amount_usd": 250}, labels=hw.Labels(),
))
decision.effect   # PolicyEffect.REQUIRE_APPROVAL
decision.rule     # "big-refunds"
```

`harness.decide_policy` returns the engine's answer alone (`effect`, `rule`, `reason`), without the governor's other steps; `harness.authorize(...)` runs the whole governor as a dry run ([Dry runs](tools.md#dry-runs-and-policy-tests)). Over HTTP, `POST /v1/policy/evaluate` takes a `PolicyRequest` and answers with a `PolicyDecision`.

## Testing policy

Write a `policy_tests.yaml` table of calls and expected verdicts, and run `harnessweaver policy test` in CI ([Tools](tools.md#dry-runs-and-policy-tests)). Each case goes through exactly the production decision, including manifests, approval rules and the trifecta, without running anything.

## tighten

`hw.tighten(a, b)` returns the stricter of two effects (`deny` > `require_approval` > `allow`). It is how probabilistic components, such as the tool judge, are allowed to change a decision: they can only make it stricter.
