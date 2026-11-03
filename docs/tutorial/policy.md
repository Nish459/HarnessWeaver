# Policy

Your support desk can now look orders up. Customers also want refunds, and some refunds must never happen automatically: very large ones, or ones a contractor asks for. **Policy** decides, deterministically, whether a tool call may run. Its rules live in the spec, are compiled when it loads, and are tested like code.

## A tool that changes things

Add a refund tool to `helpdesk/tools.py`:

```python title="helpdesk/tools.py" hl_lines="14-16"
--8<-- "docs_src/tutorial/policy/helpdesk/tools.py"
```

Its manifest says what makes it dangerous: it writes to an external system, it's high risk, and it sends data to the payment provider (`egress`):

```yaml title="tools/refund_payment.tool.yaml"
--8<-- "docs_src/tutorial/policy/tools/refund_payment.tool.yaml"
```

`rate_limit` lets each person make at most five refunds an hour (governor step 5). Pin it with `uv run harnessweaver tools pin harness.yaml`, offer it to the `orders` task with `tools: [lookup_order, refund_payment]`, and tell the model about it in a new prompt version:

```markdown title="prompts/orders@2.md"
--8<-- "docs_src/tutorial/policy/prompts/orders@2.md"
```

## Write the rules

```yaml title="harness.yaml (the policy section)"
--8<-- "docs_src/tutorial/policy/harness.yaml:44:52"
```

Each rule has an `id`, a cel-lite `when` that says when it applies, and an `effect`: `allow`, `deny` or `require_approval`. The optional `reason` is reported with the decision. A rule can read who the run acts for (`principal`, `tenant`), the `task`, the `tool` (its `name`, `side_effect`, `risk`, `egress`, ...), the call's `args`, and the run's `labels`.

## Run it

Ask for a small refund and a big one:

```python title="main.py"
--8<-- "docs_src/tutorial/policy/main.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed: Done: the refund is on its way to your card.
blocked (policy_denied): refunds over $500 go to the finance desk
```

The $900 refund never reached the tool: the governor stopped it at step 3, and the run ended `blocked` with the rule's reason. The model can't talk its way around a rule, because the rule runs on the final arguments, after any middleware.

## How rules combine

Every policy engine combines the rules the same way:

1. Take the rules whose `when` is true.
2. `deny` beats `require_approval`, which beats `allow`. Among rules with the same effect, the first one decides, and its `id` and `reason` are reported.
3. A `when` that can't be evaluated **never loosens** a decision: a `deny` or `require_approval` rule whose `when` fails counts as matching, and an `allow` rule whose `when` fails doesn't.
4. When no rule matches, `policy.default_effect` decides. It's `allow` unless your spec or baseline says otherwise.

So a rule set reads as a list of exceptions to the default. With `default_effect: allow`, write the `deny` and `require_approval` rules for what must be stopped or checked. With `default_effect: deny`, write `allow` rules for what is permitted.

!!! warning "Only deterministic components decide"
    A policy engine must be deterministic (RULES R3). Classifiers, LLM judges and semantic routers may make a decision **stricter**, by asking for approval or blocking, but they can never turn a deny into an allow. `hw.tighten(a, b)` returns the stricter of two effects, and that is the only way such a component can change a decision.

## Rules for starting a run

A rule with `hook: run.start` decides whether a run may start at all, before any work. It can read `principal`, `tenant`, `task` and `labels`:

```yaml
policy:
  rules:
    - { id: known-callers, hook: run.start, when: "principal.id == 'anonymous'", effect: deny }
```

A `run.start` rule can only restrict: `deny` blocks the run, and `require_approval` escalates it, because a run can't wait for a person before it starts.

## Test the policy

A policy is code, so test it. Write the calls you care about, and the decision you expect, in `policy_tests.yaml`:

```yaml title="policy_tests.yaml"
--8<-- "docs_src/tutorial/policy/policy_tests.yaml"
```

```console
$ uv run harnessweaver policy test harness.yaml -e offline
ok   small-refund: allow at step 7
ok   over-the-cap: block at step 3
ok   contractor: block at step 3
ok   bad-order-id: block at step 2
4 of 4 policy tests passed
```

Each case goes through the real governor (the manifests, the schema, the rules, the trifecta) as a dry run: nothing executes and no rate limit is used up. The command exits 1 when a verdict differs, so it belongs in CI. In code, `harness.authorize(tool, args, principal=...)` returns the same verdict for one call, and `harness.decide_policy(request)` returns the policy engine's answer alone.

## Engines

| Engine | From | Notes |
| --- | --- | --- |
| `cel_lite` | The core | The default. The same in Python and TypeScript |
| `cel.policy` | `harnessweaver-cel` | Full CEL. Stricter about types: `1 + 0.5` is an error, which makes the rule unevaluable, so deny and approval rules still apply |

Choose one with `policy.use`. Cedar, OPA and OpenFGA engines are *planned*.

## Recap

- `policy.rules` decide whether a tool call (or a run) may go ahead: `allow`, `deny` or `require_approval`.
- `deny` beats `require_approval` beats `allow`, and a rule that can't be evaluated never loosens a decision.
- `policy_tests.yaml` and `harnessweaver policy test` check the real decisions in CI.
