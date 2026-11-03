# Versioned prompts

A prompt is part of your app's behavior, so HarnessWeaver keeps prompts in files, versions them, and names the exact version in the spec. A change to a prompt is then a reviewed change, and every run's trace says which version it used.

## A prompt file

Create `prompts/triage@1.md`:

```markdown title="prompts/triage@1.md"
--8<-- "docs_src/tutorial/prompts/prompts/triage@1.md"
```

The file name is `<name>@<version>.md`. The version can be `1`, `1.2` or `1.2.0`, and `.txt` works as well as `.md`.

## Use it in the task

```yaml title="harness.yaml" hl_lines="21"
--8<-- "docs_src/tutorial/prompts/harness.yaml"
```

The `direct` runner sends the prompt as the **system** message and the task's input as the **user** message. Run it as before:

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed
billing, priority 2: charged twice for the Pro plan, wants one refund.
```

## Picking a version

| Reference | Picks |
| --- | --- |
| `triage@1.2.0` | Exactly that version |
| `triage@1` | The file named `triage@1.md`, or else the highest `1.x.y` |
| `triage` | The highest version, or the unversioned `triage.md` |

Name an exact version in production specs, so a new prompt file can't change behavior until the spec says so.

!!! tip
    Prompts live in `prompts/` next to the spec. Set `prompts.dir` to keep them elsewhere.

## Placeholders

A prompt can hold placeholders in braces, such as `{text}`. For a task, they are filled from the input's fields, and `{input}` is the whole input. In your own code, `s.prompt("triage@1", text=...)` renders one with the values you pass ([Sessions](sessions.md)).

```text
Summarize this message from a {plan} customer: {text}
```

Placeholders follow Python's `str.format_map`: `{{` and `}}` are literal braces, and a missing value is an error, not an empty string. HarnessWeaver has no template language with loops or conditions. Build any text that needs logic in your code, and pass it in as a value.

## Recap

- Prompts are files named `<name>@<version>.md` in `prompts/`.
- A task's `prompt` names one, and the `direct` runner sends it as the system message.
- Placeholders are filled from the input's fields, with no template language.
