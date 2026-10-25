# Quickstart

This walk takes you from nothing to a governed, traced and tested task in about fifteen minutes. Everything runs offline: no API keys, no network calls to a model, no spend. At the end you will have your own project with a typed task, PII redaction, an output check, a budget, a golden eval set with a baseline, and a new guard in shadow mode.

> **Packages aren't published yet** (0.1.0 is in preparation), so this guide installs HarnessWeaver from a clone of the repository and runs your project with that installation.

## 1. Install

You need [git](https://git-scm.com/) and [uv](https://docs.astral.sh/uv/getting-started/installation/). uv installs a suitable Python (3.12 or later) on its own if you don't have one.

```bash
git clone https://github.com/Wise-DreamerZ/HarnessWeaver.git
cd HarnessWeaver
uv sync --all-packages
```

`uv sync --all-packages` creates `.venv/` with the core (`harnessweaver`), the CLI (`harnessweaver`), the sidecar (`harnessd`), the first-party plugins and the development tools.

## 2. See a governed run

Example 01 turns the text of a supplier invoice into a typed `Invoice`:

```bash
HARNESSWEAVER_ENV=offline uv run python examples/01_invoice_extraction/run.py
```

```text
status: completed
invoice: INV-2026-0042 from Northwind Supplies Ltd
total: 1860.00 EUR over 2 lines
cost: $0.000510
```

`HARNESSWEAVER_ENV=offline` applies the example's `harness.offline.yaml` overlay, which swaps the model gateway for a scripted model. That model's first answer is deliberately invalid, so this run already shows the harness asking for a repair. The app's own code is one `harness.run(...)` call: the redaction, the repair, the budget and the trace all come from its `harness.yaml`.

## 3. Start your own project

```bash
uv run harnessweaver init ../ticket-triage
```

```text
created 10 files in ../ticket-triage from the extraction template
```

The `extraction` template (the default; `-t rag`, `-t agent`, `-t workflow` and `-t chat` give the others) creates a support-ticket triage app:

| File | What it is |
| --- | --- |
| `harness.yaml` | The spec: it extends `profile://extraction` (PII redaction on input, a secrets check on output, one repair), names the model gateway, and defines the `extract` task with its input and output types, prompt and budget, a business rule and an eval suite |
| `harness.offline.yaml` | The offline overlay: a scripted model with one answer per golden case |
| `app/models.py` | `Message` (the input) and `TicketSummary` (the typed output the model must return) |
| `app/main.py` | Runs the task once |
| `prompts/extract@1.md` | The versioned prompt |
| `evals/golden.yaml` | Two golden cases and their graders |
| `tests/test_extract.py` | Offline tests of the task and its controls |

Open `harness.yaml`; it is short. Everything the harness does in the steps below comes from it and from the profile it extends.

## 4. Check the spec

```bash
uv run harnessweaver spec validate ../ticket-triage/harness.yaml -e offline
```

```text
ok: ticket-triage is valid
  adoption level L1 (required: L0)
  layers: profile://defaults, profile://extraction, harness.yaml (../ticket-triage/harness.yaml), harness.offline.yaml (../ticket-triage/harness.offline.yaml)
  tasks: extract
```

`spec validate` loads the spec exactly as the app will: every layer, every lock and bound, every plugin, provider and task. A spec that can't run never gets past this step. The output lists the layers that were merged, in order, and the [adoption level](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/concepts/adoption-levels.md) the spec reaches.

```bash
uv run harnessweaver doctor ../ticket-triage/harness.yaml -e offline
```

```text
OK    level          adoption level L1; risk tier 'internal' requires L0
OK    next level     to reach L2: policy.rules has at least one rule
OK    hooks          task extract: runner direct reaches every hook it needs
...
```

`doctor` adds advice: what the next level needs, retry owners, unpinned profiles, guards in shadow mode and content capture.

```bash
uv run harnessweaver hooks ../ticket-triage/harness.yaml -e offline --task extract
```

This prints the middleware on each of the 13 hook points, in the order it runs. For this project: the profile's PII guard on `input.before`, and the profile's secrets check and your business rule on `output.before`.

## 5. Run the task

Your project has its own `pyproject.toml`, but until the packages are published it runs with the clone's installation, so pass `--project ../HarnessWeaver` to `uv run`:

```bash
cd ../ticket-triage
HARNESSWEAVER_ENV=offline uv run --project ../HarnessWeaver python -m app.main
```

```text
status: completed
output: {'category': 'billing', 'priority': 2, 'product': 'Pro plan', 'summary': 'The customer was charged twice for the Pro plan and wants a refund.'}
```

## 6. See what the harness did

Every run keeps a trace of every hook that fired and every decision made. Save this as `show_trace.py` in `ticket-triage/`:

```python
"""Run the task once and print what the harness did at each hook point."""

import asyncio

import harnessweaver as hw
from harnessweaver.testing import render_trace

from app.models import Message


async def main() -> None:
    harness = hw.load("harness.yaml")
    message = Message(text="I was charged twice for my Pro plan. - ann@example.com")
    result = await harness.run("extract", message, principal="demo")
    print(render_trace(result))


asyncio.run(main())
```

```bash
HARNESSWEAVER_ENV=offline uv run --project ../HarnessWeaver python show_trace.py
```

```text
   0 hook    run.start         harness -> continue
   1 note    -                 harness.guard (guard_fired): guardrails.input[extraction-pii] redact
   2 outcome input.before      guardrails.input[extraction-pii] [platform] -> continue: guardrails.input[extraction-pii]: found EMAIL
   3 hook    input.before      harness -> continue: guardrails.input[extraction-pii]: found EMAIL
   4 hook    model.before      harness -> continue
   5 note    model.after       harness.budget: model usage
   6 hook    model.after       harness -> continue
   7 outcome output.before     guardrails.output[extraction-secrets] [platform] -> continue
   8 outcome output.before     validation.rules[summary-length] [app] -> continue
   9 hook    output.before     harness -> continue
  10 hook    run.end           harness -> continue
```

Read it top to bottom. The PII guard found the e-mail address and redacted it before the model saw anything (events 1 to 3), so the model only received `[EMAIL]`. The budget recorded the call's usage (event 5). The secrets check and your `summary-length` rule passed the output (events 7 and 8). The trace never holds the content itself, only ids, codes and reasons (RULES R9). The same events become OpenTelemetry spans when you turn [observability](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/modules/observability.md) on.

## 7. Test it

Go back to the clone and run the project's tests. `harnessweaver test` sets test mode (live providers refuse to call out) and applies the offline overlay, then runs pytest:

```bash
cd ../HarnessWeaver
uv run harnessweaver test ../ticket-triage
```

```text
../ticket-triage/tests/test_extract.py .....                                     [100%]
5 passed
```

## 8. Grade it

```bash
uv run harnessweaver eval run ../ticket-triage/harness.yaml -e offline --update-baseline
```

```text
ok: golden (extract): 2/2 passed, pass rate 1.0 (threshold 0.9)
  baseline written to ../ticket-triage/.harness/baselines/extract.golden.json
```

`eval run` runs every case in `evals/golden.yaml` through the task and grades it. With `--update-baseline` it saves the results; from then on, a case that passed in the baseline and fails now is a regression, and `eval run` exits 1. Commit the baseline and run `eval run` in CI.

## 9. Add a guard, safely

New guards start in shadow mode: they record what they would have done and change nothing (RULES R8).

```bash
uv run harnessweaver add guard injection.heuristic ../ticket-triage/harness.yaml
```

```text
added guardrails.input[injection-heuristic] (injection.heuristic) in shadow mode (mode: log_only)
  promote it with mode: enforce once the eval shadow report backs it (R8)
```

The command edits `harness.yaml` (comments are kept, and an edit that doesn't load is taken back). Run the evals again and they report how often the new guard would fire:

```bash
uv run harnessweaver eval run ../ticket-triage/harness.yaml -e offline
```

```text
ok: golden (extract): 2/2 passed, pass rate 1.0 (threshold 0.9)
  shadow guardrails.input[injection-heuristic]: would fire on 0/2 (0.0); false positives: none; misses: none
```

When the evidence backs it, promote the guard with a reviewed one-line change: `mode: log_only` becomes `mode: enforce`.

## 10. Call a real model

The template points at a [LiteLLM Proxy](https://docs.litellm.ai/docs/simple_proxy) gateway, which holds the provider keys and owns retries and fallbacks:

```yaml
models:
  provider: openai.chat
  base_url: http://localhost:4000
  api_key_env: LITELLM_API_KEY
  default: fast
  aliases: { fast: your-fast-model }
```

Run a gateway (or `uv run harnessweaver dev ../ticket-triage/harness.yaml --up` for a local stack with LiteLLM, an OpenTelemetry collector and Langfuse), map the `fast` alias to a model it serves, set `LITELLM_API_KEY`, and run without `HARNESSWEAVER_ENV=offline`. Any OpenAI-compatible endpoint works the same way, and `provider: anthropic.messages` calls Claude directly. See [Models](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/modules/models.md).

## Already have an app?

You don't need tasks to start. Three lines govern the client an app already has (level L0): every call is traced, costed and budgeted, and the spec's guards run on its input and output, with redactions written back into the request.

```python
import harnessweaver as hw                                    # 1

harness = hw.load("harness.yaml")                             # 2
client = harness.instrument(AsyncOpenAI(base_url=GATEWAY))    # 3
# The rest of the app uses `client` exactly as before.
```

[`examples/01_invoice_extraction/l0_instrument.py`](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/examples/01_invoice_extraction/l0_instrument.py) runs this offline.

## Where next

- [Concepts](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/concepts/index.md): hook points, the hook bus, outcomes, the envelope and the integration styles.
- [The spec](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/spec/index.md): every section of `harness.yaml`, layering, locks and bounds.
- [Examples](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/getting-started/examples.md): a RAG support assistant, a tool-using agent with approvals, and the same spec from TypeScript and over HTTP.
- [Extending](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/extending/index.md): your own guards, middleware and plugins.
