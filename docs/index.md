# HarnessWeaver

<style>
.md-content .md-typeset h1 { display: none; }
</style>

<p align="center" class="hw-hero">
  <img src="assets/logo.svg" alt="HarnessWeaver" width="160">
</p>
<p align="center" class="hw-tagline">
  <em>The composable AI harness framework. Weave your own AI harness: bring your models, choose your plugins, define your execution.</em>
</p>
<p align="center">
  <img src="https://img.shields.io/badge/python-3.12%2B-3080ff" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/typescript-node%2022%2B-3080ff" alt="Node 22+">
  <img src="https://img.shields.io/badge/license-Apache--2.0-ac4bff" alt="License: Apache-2.0">
</p>

---

**Source Code**: [github.com/Wise-DreamerZ/HarnessWeaver](https://github.com/Wise-DreamerZ/HarnessWeaver)

---

HarnessWeaver is a framework for building **your own AI harness**: the controls every AI application needs around its models, declared in one `harness.yaml` and applied at 13 fixed hook points, whatever executor your app already uses.

The key features are:

- **Declarative**: tracing, cost, budgets, guardrails, typed output, tool governance, policy, approvals, routing, retrieval governance and evals, all in one spec. Your code stays one call.
- **Non-invasive**: keep the executor you have, whether raw SDK calls, Pydantic AI, the Vercel AI SDK or your own pipeline. Govern an existing client in three lines.
- **Safe by default**: the org baseline can't be removed by an app, controls fail closed, and no prompt or output reaches a log or a span unredacted.
- **Composable**: every capability is a module behind a port, with providers you swap, and plugins anyone can write in their own repository.
- **Polyglot**: one spec serves Python, TypeScript, and any language through the harnessd sidecar.
- **Testable**: everything runs offline against fakes, with no network and no model spend, and every decision is in a trace your tests can check.
- **Standards-based**: OpenTelemetry GenAI conventions, JSON Schema contracts, an OpenAPI sidecar, and a CEL subset for rules.

## Requirements

Python 3.12 or later. The core depends only on [Pydantic](https://docs.pydantic.dev/), the [OpenTelemetry API](https://opentelemetry.io/), [PyYAML](https://pyyaml.org/), [anyio](https://anyio.readthedocs.io/) and [loguru](https://loguru.readthedocs.io/). Everything else is a plugin.

## Installation

```console
$ uv add "harnessweaver[openai]"
```

No project yet? Make one first with `uv init --python 3.12 support-desk && cd support-desk`. Or let the [Quickstart](learn/quickstart.md) create a whole project from a template, then run, trace, test and grade it offline and call a real model, in about ten minutes.

## Example

### Create it

Create a `harness.yaml`:

```yaml title="harness.yaml"
--8<-- "docs_src/tutorial/first_steps/harness.yaml"
```

And a `main.py`:

```python title="main.py"
--8<-- "docs_src/tutorial/first_steps/main.py"
```

To run without a model gateway, add `harness.offline.yaml`, which swaps the model for a scripted one:

```yaml title="harness.offline.yaml"
--8<-- "docs_src/tutorial/first_steps/harness.offline.yaml"
```

### Run it

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed
billing, priority 2: charged twice for the Pro plan, wants one refund.
```

### Check it

Every run keeps a trace of the hook points it passed and every decision made, with no content in it. Print it with `harnessweaver.testing.render_trace(result)`:

```text
   0 hook    run.start         harness -> continue
   1 hook    input.before      harness -> continue
   2 hook    model.before      harness -> continue
   3 note    model.after       harness.budget: model usage
   4 hook    model.after       harness -> continue
   5 hook    output.before     harness -> continue
   6 hook    run.end           harness -> continue
```

## Example upgrade

Now give the task typed output, the `extraction` profile's guards, a business rule and a budget, all in the spec:

```yaml title="harness.yaml" hl_lines="6 18-21 23-27"
--8<-- "docs_src/home/harness.yaml"
```

The types are plain Pydantic models:

```python title="helpdesk/models.py"
--8<-- "docs_src/home/helpdesk/models.py"
```

The app is still one call:

```python title="main.py"
--8<-- "docs_src/home/main.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
billing, priority 2: Charged twice for the Pro plan and wants one payment refunded.
completed
harness.guard (guard_fired): guardrails.input[extraction-pii] redact
```

The customer's e-mail address was redacted before the model saw it, and the guard's firing is in the trace.

### Recap

With a few lines of YAML, and no change to how the app calls the harness, the task now has:

- **Typed output**: the answer is parsed into `Triage`, and the category and priority are checked against the type.
- **Repair**: an answer that doesn't parse, or breaks `bugs-are-urgent`, is sent back to the model with the reason, once, and then escalated to a person.
- **Guards**: e-mail addresses, phone numbers and card numbers are redacted from the input, and secrets are blocked in the output.
- **A budget**: at most three model calls, one cent and thirty seconds per run, checked before every call.
- **A trace**: every guard, rule, repair and budget check, without any content.

And the same spec, extended by your org's baseline, can't have its required controls switched off.

The [Tutorial](tutorial/index.md) builds a complete support desk this way, with routing, retrieval, tools, policy, approvals, state, observability, tests and evals.

## Already have an app?

Govern the client it already uses, without changing the code that calls it:

```python
client = harness.instrument(AsyncOpenAI(base_url="http://localhost:4000"), tenant="acme")
reply = await client.chat.completions.create(model="fast-chat", messages=messages)   # traced, costed, budgeted, guarded
```

See [Govern an existing client](how-to/wrap-a-client.md).

## Not an agent framework

HarnessWeaver isn't an agent framework, a prompt library, a vector database or a model host, and it never does the reasoning itself (RULES R12). It puts controls around the executor your app already uses. [Alternatives and comparisons](about/alternatives.md) compares it with the tools around it.

## Dependencies

The core, `harnessweaver`, depends on:

- `pydantic`: every spec, contract and payload is a Pydantic model.
- `opentelemetry-api`: spans and metrics, without an SDK unless you add one.
- `pyyaml`: specs are YAML 1.2.
- `anyio`: async everywhere.
- `loguru`: logs, silent until your app enables them.

Optional plugins, installed with extras such as `harnessweaver[openai]`:

- `harnessweaver-openai`: any OpenAI-compatible endpoint (LiteLLM Proxy, OpenAI, vLLM, Ollama).
- `harnessweaver-anthropic`: Claude, through the Messages API.
- `harnessweaver-pydantic-ai`: Pydantic AI agents, as a runner or wrapped.
- `harnessweaver-otel`: OpenTelemetry SDK setup and export.
- `harnessweaver-cel`: full CEL for policy rules.
- `harnessweaver-monty`: a sandbox for code-executing tools.

And the tools: `harnessweaver-cli` (the `harnessweaver` command) and `harnessweaver-sidecar` (`harnessd`).

## License

This project is licensed under the terms of the Apache-2.0 license.
