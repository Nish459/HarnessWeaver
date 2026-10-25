# Your own steps: sessions

The `direct` runner does one thing: send the input to the model and return the answer. Many tasks are more than that: decide what kind of question this is, fetch some documents, then ask the model. In a **session**, your code owns those steps, and the harness governs each one: every model call, tool call and retrieval passes the same hooks, guards and budgets as a runner's.

This chapter adds a second task, `answer`, written as a session.

## Write the steps

Add `helpdesk/flows.py`:

```python title="helpdesk/flows.py"
--8<-- "docs_src/tutorial/sessions/helpdesk/flows.py"
```

`s` is a `Session`. `s.generate` renders the prompt `answer@1` with `question`, sends it to the model as a user message, and returns the answer. The model call is governed exactly as a task's is. Add the prompt:

```markdown title="prompts/answer@1.md"
--8<-- "docs_src/tutorial/sessions/prompts/answer@1.md"
```

## Run the steps as a task

Add the `answer` task, with the `session` runner pointing at your function:

```yaml title="harness.yaml (tasks and validation)" hl_lines="13-16 21 24"
--8<-- "docs_src/tutorial/sessions/harness.yaml:22:46"
```

Notice the rules changed too. Rules check every task's output, and `answer` returns plain text, which has no `category` or `summary`. A rule that can't be evaluated counts as broken, so without `task.name == 'triage'` every answer would be sent back for repair.

Give the offline model an answer for questions:

```yaml title="harness.offline.yaml"
--8<-- "docs_src/tutorial/sessions/harness.offline.yaml"
```

```python title="main.py"
--8<-- "docs_src/tutorial/sessions/main.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed
Refunds go back to the card you paid with within five business days.
```

As a task, `answer` gets everything a task has: the input guards run on the question before your function sees it, the task's budget applies, the output is checked, and the run can be retried by idempotency key, suspended for approval and resumed, and graded by evals.

`principal` and `tenant` say who the run acts for. Policy rules, retrieval ACLs and rate limits all read them, as later chapters show.

## Or open a session yourself

In an app that already has its own request handling, you can open a session around your code instead of defining a task's runner:

```python title="main_session.py" hl_lines="10-13"
--8<-- "docs_src/tutorial/sessions/main_session.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main_session.py
How long does a refund take? I'm [EMAIL]
Refunds go back to the card you paid with within five business days.
```

`harness.session("answer", ...)` opens one run with the `answer` task's budget and controls. Nobody hands a standalone session its input, so the input guards run when your code asks: `s.guard("input", ...)` returned the question with the e-mail address redacted. When the `async with` block ends, `run.end` fires and the run's result is kept.

## What a session can do

| Method | What it does | Hook point |
| --- | --- | --- |
| `s.guard("input", content)` | Runs the input guards; returns the content, possibly redacted | `input.before` |
| `s.decide(router, text=...)` | Asks a router to choose ([Routing](routing.md)) | `route.decide` |
| `s.context(source).fetch(query)` | Retrieves items, governed ([Retrieval](context.md)) | `context.after` |
| `s.context(source).check(items)` | Governs items your own code retrieved | `context.after` |
| `s.generate(prompt=..., output=..., model=..., **variables)` | A governed model call; `output` parses into a type and repairs | `model.before`, `model.after`, `output.before` |
| `s.tool(name, **arguments)` | A governed tool call; returns its output ([Tools](tools.md)) | `tool.before`, `tool.after` |
| `s.validate("output", value, output=...)` | Checks an output you produced yourself | `output.before` |
| `s.prompt(ref, **variables)` | Renders a versioned prompt without calling a model | - |
| `s.memory` | Key-value entries for this tenant, principal and task ([Retrieval and memory](context.md#memory)) | - |
| `s.run_id`, `s.envelope`, `s.trace` | The run's id, its envelope and its trace so far | - |

A control that stops the run, such as a guard that blocks or a budget that runs out, raises a `RunInterrupted` error in your code: `RunBlocked` or `RunEscalated`. Your code doesn't need to catch it, because the run is over either way.

!!! info "Task or standalone?"
    A standalone session can't be suspended and resumed later, because the harness can't re-enter your code. So in a standalone session, a request for approval **escalates** instead. As a task (`runner: session`), the same function suspends, and after an approval it runs again from the start. The approved call then passes without asking again.

## Three ways to adopt HarnessWeaver

You have now used two of the three integration styles:

| Style | You write | The harness guarantees |
| --- | --- | --- |
| **Run** (`harness.run` with `direct`) | A task in the spec | Every hook, plus idempotency, approvals that suspend and resume, and repairs |
| **Session** (`runner: session` or `harness.session`) | The steps, in your code | Every hook your code asks for |
| **Wrap** (`harness.instrument(client)`) | Nothing new: your existing client | Every call it makes is traced, costed, budgeted and guarded |

[Integration styles](../concepts/integration-styles.md) compares them, and [Govern an existing client](../how-to/wrap-a-client.md) shows the third.

## Recap

- A **session** runs your code's steps, each governed: `s.generate`, `s.tool`, `s.context`, `s.decide`, `s.guard`.
- `runner: { use: session, handler: ... }` makes a function a task. `harness.session(...)` opens one around existing code.
- Rules check every task's output, so scope them with `task.name`.
