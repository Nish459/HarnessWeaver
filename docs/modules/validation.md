# Validation

Validation makes sure a run's output is what the app expects: the right type, and within the app's business rules. An output that fails is sent back to the model with the reasons, a bounded number of times, and then the run ends as the spec says. The app never writes a retry loop.

```yaml
validation:
  max_repairs: 1             # default 1
  on_failure: escalate       # or block (the default)
  rules:
    - { id: summary-length, when: "size(output.summary) > 200", message: "keep the summary under 200 characters" }
    - { id: urgent-bugs, when: "output.category == 'bug' && output.priority > 2", message: "a bug is priority 1 or 2" }
tasks:
  extract: { runner: direct, output: app.models:TicketSummary, prompt: extract@1 }
```

## Typed output

A task's `output` names a Pydantic model (`package.module:Model`), or `str` for plain text. The model is asked for structured output (the provider sends the schema in the form its API expects), and the answer is parsed into the type. In a session, `s.generate(output=Model)` does the same.

```python
class TicketSummary(BaseModel):
    category: Literal["billing", "bug", "account", "other"]
    priority: int = Field(ge=1, le=4, description="1 is the most urgent.")
    product: str
    summary: str
```

Declaring `output` for every task is an [L1 requirement](../concepts/adoption-levels.md) (`L1.task_outputs`).

## Repair

When the answer doesn't parse, or an `output.before` middleware asks for a repair (a business rule, `grounded.citations`, your own guard with `action: repair`):

1. The problem is recorded as a `repair` trace note, with field locations and messages only, never the values (RULES R9).
2. The model's answer and a repair request go back to the model: *"Your previous answer was not accepted: {problem}. Reply again with a corrected answer in the required format."*
3. The new answer is checked again, with `attempt` one higher on the `output.before` event.
4. After `max_repairs` failed repairs, the run ends as `on_failure` says: `block` (the default) or `escalate`, with code `validation_failed`.

Repairs don't count against the `direct` runner's `max_steps`, but each one is a model call, so it counts against the budget.

## Business rules

`validation.rules` are cel-lite expressions over `output`, `input` and `task`, installed as `output.before` middleware in the band of the layer that declared them ([ADR-0023](../adr/0023-validation-rule-when.md)):

- A rule's `when` describes a **violation**: true means the output breaks the rule, like a policy rule's `when` describes when it applies.
- A true `when`, **or one that can't be evaluated** (a missing field, a type mismatch), asks for a repair with the rule's `message`. A rule that can't be checked fails closed.
- Rules are compiled when the spec loads, so a typo fails then, not mid-run.
- Each rule appears in `harnessweaver hooks` as `validation.rules[<id>]`.

Because a rule that can't be evaluated counts as broken, write rules for the output's actual shape: rules about a typed object don't belong in a spec whose outputs are plain text.

## Validating an output you produced

In a session, `s.validate("output", value, output=Model)` parses `value` into `Model` (when given) and runs `output.before` on it, returning the output as the middleware left it. When the value doesn't parse, or a middleware asks for a repair, it raises `ValidationFailed` with the reason, and your code decides whether to ask the model again: the session doesn't own your model call. `s.validate` works the same in TypeScript ([Example 04](../getting-started/examples.md#example-04-one-spec-every-language) makes one repair). `s.generate(output=Model)`, by contrast, owns the call, so it repairs by itself up to `max_repairs` and then ends the run as `on_failure` says.

## Schema validation of tool arguments

Tool arguments are validated against each manifest's `input_schema` by a small JSON Schema 2020-12 validator in the core: types, `enum` and `const`, object, array, string and number keywords, `allOf`, `anyOf`, `oneOf`, `not`, and `$ref` to `#/$defs`. Annotations are ignored; any other keyword fails the manifest at load, so a schema never checks less than it says ([ADR-0026](../adr/0026-json-schema-subset.md)). Problems name locations and rules, never values.
