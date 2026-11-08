# Quickstart

This walk takes you from nothing to a governed, traced and tested task of your own in about ten minutes, and then to a real model. Until that last step everything runs offline: no API keys, no network calls to a model, no spend. At the end you will have a project with a typed task, PII redaction, an output check, a budget, a golden eval set with a baseline, and a new guard in shadow mode.

## 1. Install uv

HarnessWeaver is a set of Python packages on PyPI, and [uv](https://docs.astral.sh/uv/) installs them. If you don't have uv yet:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows, or to install it another way, see [uv's installation guide](https://docs.astral.sh/uv/getting-started/installation/). You don't need to install Python yourself: uv finds or downloads a suitable one (3.12 or later).

## 2. Create a project

```bash
uvx --from harnessweaver-cli harnessweaver init ticket-triage
cd ticket-triage
uv sync
```

```text
created 10 files in ticket-triage from the extraction template
```

`uvx` runs the `harnessweaver` command once without installing it, and `init` writes a project from a template. `uv sync` installs the project's dependencies into `ticket-triage/.venv/`: the core (`harnessweaver`), the plugin for OpenAI-compatible models (`harnessweaver-openai`) and, for development, the CLI and pytest. From here on, every command runs inside `ticket-triage/`, and `uv run harnessweaver` is the project's own copy of the CLI.

> If `uvx` says the current Python version doesn't satisfy `Python>=3.12`, your default Python is older: run `uvx --python 3.12 --from harnessweaver-cli harnessweaver init ticket-triage` instead.

The `extraction` template (the default; `-t rag`, `-t agent`, `-t workflow` and `-t chat` give the [others](https://harnessweaver.wisedreamerz.com/docs/resources/templates/)) is a support-ticket triage app:

| File | What it is |
| --- | --- |
| `harness.yaml` | The spec: it extends `profile://extraction` (PII redaction on input, a secrets check on output, one repair), names the model, and defines the `extract` task with its input and output types, prompt and budget, a business rule and an eval suite |
| `harness.offline.yaml` | The offline overlay: a scripted model with one answer per golden case |
| `app/models.py` | `Message` (the input) and `TicketSummary` (the typed output the model must return) |
| `app/main.py` | Runs the task once |
| `prompts/extract@1.md` | The versioned prompt |
| `evals/golden.yaml` | Two golden cases and their graders |
| `tests/test_extract.py` | Offline tests of the task and its controls |

Open `harness.yaml`; it is short. Everything the harness does in the steps below comes from it and from the profile it extends.

## 3. Run the task

```bash
HARNESSWEAVER_ENV=offline uv run python -m app.main
```

```text
status: completed
output: {'category': 'billing', 'priority': 2, 'product': 'Pro plan', 'summary': 'The customer was charged twice for the Pro plan and wants a refund.'}
```

`HARNESSWEAVER_ENV=offline` merges `harness.offline.yaml` over `harness.yaml`, which swaps the model gateway for a scripted model, so the run needs no network, no keys and no money. The app's own code, in `app/main.py`, is one call:

```python
result = await harness.run("extract", Message(text=SAMPLE), principal="demo")
```

There is no retry loop, no error handling around the model and no tracing setup. The redaction, the output check, the budget and the trace all come from `harness.yaml`.

## 4. See what the harness did

Every run keeps a trace of every hook that fired and every decision made. Save this as `show_trace.py`:

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
HARNESSWEAVER_ENV=offline uv run python show_trace.py
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

Read it top to bottom. The PII guard found the e-mail address and redacted it before the model saw anything (events 1 to 3), so the model only received `[EMAIL]`. The budget recorded the call's usage (event 5). The secrets check and your `summary-length` rule passed the output (events 7 and 8). The trace never holds the content itself, only ids, codes and reasons (RULES R9). The same events become OpenTelemetry spans when you turn on [observability](https://harnessweaver.wisedreamerz.com/docs/tutorial/observability/).

## 5. Check the spec

```bash
uv run harnessweaver spec validate -e offline
```

```text
ok: ticket-triage is valid
  adoption level L1 (required: L0)
  layers: profile://defaults, profile://extraction, harness.yaml (harness.yaml), harness.offline.yaml (harness.offline.yaml)
  tasks: extract
```

`spec validate` loads the spec exactly as the app will: every layer, every lock and bound, every plugin, provider and task. A spec that can't run never gets past this step. The output lists the layers that were merged, in order, and the [adoption level](https://harnessweaver.wisedreamerz.com/docs/concepts/adoption-levels/) the spec reaches. With no path, the CLI reads `harness.yaml` in the current directory.

```bash
uv run harnessweaver doctor -e offline
```

```text
OK    level          adoption level L1; risk tier 'internal' requires L0
OK    next level     to reach L2: policy.rules has at least one rule
OK    hooks          task extract: runner direct reaches every hook it needs
...
```

`doctor` adds advice: what the next level needs, retry owners, unpinned profiles, guards in shadow mode and content capture.

```bash
uv run harnessweaver hooks -e offline --task extract
```

This prints the middleware on each of the 13 hook points, in the order it runs. For this project: the profile's PII guard on `input.before`, and the profile's secrets check and your business rule on `output.before`.

## 6. Test it

```bash
uv run harnessweaver test
```

```text
collected 5 items

tests/test_extract.py .....                                              [100%]

============================== 5 passed in 0.05s ===============================
```

`harnessweaver test` runs pytest in test mode (live providers refuse to call out) with the offline overlay applied, so tests can never reach a real model by accident.

## 7. Grade it

```bash
uv run harnessweaver eval run -e offline --update-baseline
```

```text
ok: golden (extract): 2/2 passed, pass rate 1.0 (threshold 0.9)
  baseline written to .harness/baselines/extract.golden.json
```

`eval run` runs every case in `evals/golden.yaml` through the task and grades it. With `--update-baseline` it saves the results; from then on, a case that passed in the baseline and fails now is a regression, and `eval run` exits 1. Commit the baseline and run `eval run` in CI.

## 8. Add a guard, safely

New guards start in shadow mode: they record what they would have done and change nothing (RULES R8).

```bash
uv run harnessweaver add guard injection.heuristic
```

```text
added guardrails.input[injection-heuristic] (injection.heuristic) in shadow mode (mode: log_only)
  promote it with mode: enforce once the eval shadow report backs it (R8)
```

The command edits `harness.yaml` (comments are kept, and an edit that doesn't load is taken back). Run the evals again and they report how often the new guard would fire:

```bash
uv run harnessweaver eval run -e offline
```

```text
ok: golden (extract): 2/2 passed, pass rate 1.0 (threshold 0.9)
  shadow guardrails.input[injection-heuristic]: would fire on 0/2 (0.0); false positives: none; misses: none
```

When the evidence backs it, promote the guard with a reviewed one-line change: `mode: log_only` becomes `mode: enforce`.

## 9. Call a real model

So far a scripted model has answered. To call a real one, replace the `models` section of `harness.yaml` with the one for your provider, set its key, and run without `HARNESSWEAVER_ENV=offline`. Tests and evals keep using the offline overlay, so they stay offline and free.

**OpenAI**, called directly:

```yaml
models:
  provider: openai.chat                  # no base_url: the OpenAI API itself
  api_key_env: OPENAI_API_KEY
  max_retries: 2                         # with no gateway, the SDK retries
  default: fast
  aliases: { fast: your-openai-model }   # a model id your account can use
```

**Claude**, called directly. Add its plugin first, with `uv add "harnessweaver[anthropic]"`:

```yaml
models:
  provider: anthropic.messages
  api_key_env: ANTHROPIC_API_KEY
  default: fast
  aliases: { fast: claude-haiku-5-5 }
```

**A local model** with [Ollama](https://ollama.com), which costs nothing and keeps everything on your machine:

```yaml
models:
  provider: openai.chat
  base_url: http://localhost:11434/v1    # Ollama's OpenAI-compatible API
  api_key_env: OLLAMA_API_KEY            # Ollama ignores the key, but one must be set
  default: fast
  aliases: { fast: your-local-model }    # one you pulled with `ollama pull`
```

**A gateway**, the template's own setting and the one for production: [LiteLLM Proxy](https://docs.litellm.ai/docs/simple_proxy) holds the provider keys, owns retries and fallbacks, and reports what each call cost. Keep the template's `models` section, map the `fast` alias to a model the gateway serves, and set `LITELLM_API_KEY`. With Docker, `uv run harnessweaver dev --up` starts one locally, with an OpenTelemetry collector and Langfuse ([Gateways and the dev stack](https://harnessweaver.wisedreamerz.com/docs/deployment/gateways/)).

Then set the key named by `api_key_env` and run the task:

```bash
export OPENAI_API_KEY=...                # or ANTHROPIC_API_KEY, OLLAMA_API_KEY=ollama, LITELLM_API_KEY
uv run python -m app.main
```

If the run doesn't complete, the app prints why:

```text
status: failed
output: None
error: provider_error: openai.chat needs $OPENAI_API_KEY
```

A provider called directly doesn't report what a call cost, so the run's cost is marked unknown (it is never guessed) and a `max_usd` budget can't count it. Add your models' prices under `models.prices` to fix that ([Models and environments](https://harnessweaver.wisedreamerz.com/docs/tutorial/models/#cost)). When the app reaches production, keep each environment's model settings in an overlay such as `harness.prod.yaml`, picked with `HARNESSWEAVER_ENV=prod`.

## Already have an app?

You don't need tasks to start. Three lines govern the client an app already has (level L0): every call is traced, costed and budgeted, and the spec's guards run on its input and output, with redactions written back into the request.

```python
import harnessweaver as hw                                    # 1

harness = hw.load("harness.yaml")                             # 2
client = harness.instrument(AsyncOpenAI(base_url=GATEWAY))    # 3
# The rest of the app uses `client` exactly as before.
```

See [Govern an existing client](https://harnessweaver.wisedreamerz.com/docs/how-to/wrap-a-client/).

## Run the examples

The repository has four complete examples: invoice extraction, a support assistant with retrieval, a refund agent with tools and approvals, and one spec served to TypeScript and over HTTP. They run offline from a clone:

```bash
git clone https://github.com/Wise-DreamerZ/HarnessWeaver.git
cd HarnessWeaver
uv sync --all-packages
HARNESSWEAVER_ENV=offline uv run python examples/01_invoice_extraction/run.py
```

[Examples](https://harnessweaver.wisedreamerz.com/docs/resources/examples/) describes each one.

## Where next

- [Tutorial](https://harnessweaver.wisedreamerz.com/docs/tutorial/): one app, a support desk, built chapter by chapter with every feature.
- [Serve it from a web app](https://harnessweaver.wisedreamerz.com/docs/how-to/web-app/): one harness for every request, each run as the user who made it, approvals over HTTP.
- [Concepts](https://harnessweaver.wisedreamerz.com/docs/concepts/): hook points, the hook bus, outcomes, the envelope and the integration styles.
- [The spec](https://harnessweaver.wisedreamerz.com/docs/concepts/spec/): every section of `harness.yaml`, layering, locks and bounds.
- [Deployment](https://harnessweaver.wisedreamerz.com/docs/deployment/): gateways, overlays, state, telemetry, CI and a production checklist.
- [Troubleshooting](https://harnessweaver.wisedreamerz.com/docs/how-to/troubleshooting/): what each load error and blocked run means, and how to fix it.
