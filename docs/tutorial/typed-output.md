# Typed output

So far `triage` returns a line of text that your code would have to parse. Give the task Pydantic types instead, and the harness asks the model for structured output, parses the answer, and checks it before your code sees it.

## Declare the types

Create a package for your app's code, `helpdesk/`, with an empty `__init__.py` and this `models.py`:

```python title="helpdesk/models.py"
--8<-- "docs_src/tutorial/typed_output/helpdesk/models.py"
```

These are ordinary Pydantic models. The `Field` constraints and descriptions are part of the contract: the model sees the descriptions, and the harness enforces the constraints.

## Use them in the task

```yaml title="harness.yaml" hl_lines="21-23"
--8<-- "docs_src/tutorial/typed_output/harness.yaml"
```

- `input` is the type the task's input is validated into, as `package.module:Name`.
- `output` is the type the model's answer is parsed into. `str` means plain text.

The prompt no longer needs to describe a reply format, so it gets a new version:

```markdown title="prompts/triage@2.md"
--8<-- "docs_src/tutorial/typed_output/prompts/triage@2.md"
```

## Run it

The offline model now answers with structured output:

```yaml title="harness.offline.yaml"
--8<-- "docs_src/tutorial/typed_output/harness.offline.yaml"
```

```python title="main.py" hl_lines="3 10-11 13-15"
--8<-- "docs_src/tutorial/typed_output/main.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed
billing, priority 2: Charged twice for the Pro plan and wants one payment refunded.
```

`result.output` is the parsed output as JSON (a `dict` here), because a `RunResult` travels between processes and languages. `Triage.model_validate(result.output)` turns it back into your type.

## What the harness did

1. It validated the input into a `Ticket`. Input that doesn't validate ends the run `failed` (code `validation_failed`) before the model is called.
2. It sent `Triage`'s JSON Schema with the request, in the form the provider's API expects (for example, OpenAI's `response_format`).
3. It parsed the answer into `Triage`: the category must be one of the four, and the priority between 1 and 4.
4. It ran the `output.before` hook on the parsed output, where output guards and business rules go.

An answer that doesn't parse is not your code's problem: the next chapter shows the harness asking the model to fix it.

!!! check
    Declaring an `output` type for every task is one of the requirements of adoption level **L1** ([Adoption levels](../concepts/adoption-levels.md)). Typed output is where governance starts: you can only check what you can name.

## Recap

- A task's `input` and `output` name Pydantic models, as `package.module:Name`.
- The harness asks for structured output, parses the answer into your type, and checks it on `output.before`.
- `result.output` is JSON. Validate it back into your model with `model_validate`.
