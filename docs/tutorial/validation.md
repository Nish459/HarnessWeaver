# Repairs and business rules

A typed output can still be wrong for your business: a crash reported as low priority, a summary that runs on for a paragraph. **Business rules** catch what the schema can't. When an answer breaks a rule, or doesn't parse at all, the harness sends it back to the model with the reason, a bounded number of times. Your code never writes a retry loop.

## Add rules

```yaml title="harness.yaml" hl_lines="25-34"
--8<-- "docs_src/tutorial/validation/harness.yaml"
```

- `max_repairs` is how many times a rejected answer is sent back to the model (the default is 1).
- `on_failure` is what happens when the last repair still fails: `block` (the default) or `escalate`, which hands the run to a person.
- Each rule has an `id`, a `when` expression and a `message` for the model.

!!! warning "A rule's `when` describes a violation"
    `when` is true when the output **breaks** the rule, the way a policy rule's `when` says when it applies. `output.category == 'bug' && output.priority > 2` reads as "a bug marked priority 3 or 4 is wrong".

The expressions are [cel-lite](../reference/expressions.md), a small, safe subset of CEL that runs the same in Python and TypeScript. They can read `output`, `input` and `task`. They are compiled when the spec loads, so a typo fails at start-up, not in the middle of a run.

## Watch a repair

Make the offline model answer wrongly first. Its rule matches the harness's repair request, so its second answer is correct:

```yaml title="harness.offline.yaml"
--8<-- "docs_src/tutorial/validation/harness.offline.yaml"
```

Run a crash report and print the trace:

```python title="main.py"
--8<-- "docs_src/tutorial/validation/main.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed
bug, priority 1: The app crashes at login since this morning's update.
   0 hook    run.start         harness -> continue
   1 hook    input.before      harness -> continue
   2 hook    model.before      harness -> continue
   3 note    model.after       harness.budget: model usage
   4 hook    model.after       harness -> continue
   5 outcome output.before     validation.rules[bugs-are-urgent] [app] -> retry: a bug is priority 1 or 2
   6 outcome output.before     validation.rules[short-summary] [app] -> continue
   7 hook    output.before     harness -> retry: a bug is priority 1 or 2
   8 note    output.before     harness.validation (repair): repair 1: a bug is priority 1 or 2
   9 hook    model.before      harness -> continue
  10 note    model.after       harness.budget: model usage
  11 hook    model.after       harness -> continue
  12 outcome output.before     validation.rules[bugs-are-urgent] [app] -> continue
  13 outcome output.before     validation.rules[short-summary] [app] -> continue
  14 hook    output.before     harness -> continue
  15 hook    run.end           harness -> continue
```

Event 5 is the rule answering `retry` with its message, and event 8 is the harness's repair. The second answer passes both rules, and the run completes. Your code only ever saw the valid answer.

## How a repair works

When an answer doesn't parse into the output type, or something on `output.before` asks for a repair (a rule, a guard with `action: repair`, your own middleware):

1. The problem is recorded as a `repair` note in the trace, with field locations and messages only, never the values (RULES R9).
2. The model's answer and a repair request go back to the model: *"Your previous answer was not accepted: {problem}. Reply again with a corrected answer in the required format."*
3. The new answer is checked again from the start.
4. After `max_repairs` failed repairs, the run ends as `on_failure` says, with the code `validation_failed`.

A repair is a model call, so it counts against the task's budget, which the next chapter sets.

## Rules that can't be checked

A rule whose `when` can't be evaluated, because of a missing field or a type mismatch, counts as **broken**: it asks for a repair. A rule that can't be checked fails closed.

So write rules for your output's real shape. Rules apply to every task's output. When you add a task with a different output type (the `answer` task in [Sessions](sessions.md)), scope your rules to the task they're for with `task.name == 'triage' && ...`.

## Validating an output you produced

In your own code ([Sessions](sessions.md)), `s.generate(output=Triage)` repairs on its own, like a task does. If you produce an output some other way, `s.validate` runs the same checks on it:

```python
checked = await s.validate("output", value, output=Triage)
```

It parses `value` into `Triage` and runs `output.before`. When something rejects it, it raises `ValidationFailed` with the reason, and your code decides whether to ask again: the session doesn't own your model call.

## Recap

- `validation.rules` are cel-lite expressions whose `when` describes a **violation**.
- A rejected answer is sent back with the reason, up to `max_repairs` times, then the run ends as `on_failure` says.
- Every repair is in the trace, and none of it is in your code.
