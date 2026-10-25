# First steps

The simplest harness has one model and one task. Create these two files in `support-desk/`:

```yaml title="harness.yaml"
--8<-- "docs_src/tutorial/first_steps/harness.yaml"
```

```python title="main.py"
--8<-- "docs_src/tutorial/first_steps/main.py"
```

## Run it offline

`harness.yaml` points at a model gateway on `localhost:4000` that you may not have yet. Add a third file, an **environment overlay**, that swaps it for a scripted model:

```yaml title="harness.offline.yaml"
--8<-- "docs_src/tutorial/first_steps/harness.offline.yaml"
```

Run the app with `HARNESSWEAVER_ENV=offline`:

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed
billing, priority 2: charged twice for the Pro plan, wants one refund.
```

`HARNESSWEAVER_ENV=offline` tells `hw.load` to merge `harness.offline.yaml` over `harness.yaml`. The overlay's `models.provider: scripted` replaces the gateway with a model that answers from a script, so the run needs no network, no keys and no money.

!!! info
    The scripted model ignores settings meant for a real provider, such as `base_url`, so the overlay only changes what it needs. Every example and test in HarnessWeaver works this way.

## Check it

Every run keeps a **trace**: one event for every hook point that fired and for every decision the harness made. Print it with `render_trace`:

```python title="main.py" hl_lines="4 12"
--8<-- "docs_src/tutorial/first_steps/main_trace.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed
billing, priority 2: charged twice for the Pro plan, wants one refund.
   0 hook    run.start         harness -> continue
   1 hook    input.before      harness -> continue
   2 hook    model.before      harness -> continue
   3 note    model.after       harness.budget: model usage
   4 hook    model.after       harness -> continue
   5 hook    output.before     harness -> continue
   6 hook    run.end           harness -> continue
```

That is the run's whole lifecycle. The input arrived (`input.before`), the request went to the model (`model.before`), its usage was recorded (`model.after`), the output was checked (`output.before`), and the run ended. Each of those names is a **hook point**, a fixed place where controls attach. There are 13 of them, and the rest of this tutorial puts controls on them.

!!! note
    A trace holds ids, codes, names and numbers, never the prompt, the input or the output (RULES R9). It is safe to log.

## Recap, step by step

### Step 1: the document

```yaml
apiVersion: harnessweaver/v1
kind: Harness
metadata:
  name: support-desk
  owner: support-team
```

Every spec starts like this. `apiVersion` is the contract version, `kind: Harness` says this is an app's spec, and `metadata.name` names the app in traces and telemetry.

### Step 2: the model

```yaml
models:
  provider: openai.chat
  base_url: http://localhost:4000
  api_key_env: LITELLM_API_KEY
  default: fast
  aliases: { fast: fast-chat }
```

`openai.chat` (from `harnessweaver-openai`) calls any OpenAI-compatible endpoint. It is usually a gateway such as [LiteLLM Proxy](https://docs.litellm.ai/docs/simple_proxy), which holds the provider keys and owns retries. The spec never holds a key: `api_key_env` names the environment variable that does.

Your code never names a concrete model. It asks for an **alias**, `fast`, and the spec says what `fast` means. [Models and environments](models.md) shows why.

### Step 3: the task

```yaml
tasks:
  triage:
    runner: direct
    output: str
```

A **task** is a named unit of work. Its `runner` decides how it executes: `direct` sends the input to the model and returns the answer. `output: str` says the answer is plain text. [Typed output](typed-output.md) turns it into a Pydantic model.

### Step 4: load the spec

```python
harness = hw.load("harness.yaml")
```

`hw.load` reads the spec and its overlay, merges them with the framework's safe defaults, checks every key, provider and task, and builds the harness. Anything wrong fails **here**, at start-up, with a `SpecError` that names the key and the file, never in the middle of a run.

### Step 5: run the task

```python
result = await harness.run("triage", "I was charged twice for my Pro plan. Refund one?")
```

`harness.run` runs the task to the end and returns a `RunResult`. Your code doesn't retry, catch model errors or set up tracing: the harness owns all of that.

| Field | What it holds |
| --- | --- |
| `status` | `completed`, `blocked`, `escalated`, `awaiting_approval`, `failed` or `cancelled` |
| `output` | The answer, when the run completed |
| `error` | Why it didn't complete: a message and a code such as `budget_exceeded` |
| `usage`, `cost_usd` | Tokens used, and what they cost |
| `trace` | Everything that happened, as above |

`result.ok` is a shortcut for `result.status == RunStatus.COMPLETED`.

## Call a real model

When you have a gateway running (or `uv run harnessweaver dev harness.yaml --up` starts a local one with LiteLLM, an OpenTelemetry collector and Langfuse), map `fast` to a model it serves, set the key and run without the overlay:

```console
$ export LITELLM_API_KEY=your-gateway-key
$ uv run python main.py
```

The rest of the tutorial keeps running offline, so you can follow it without a gateway.

## Recap

- A **spec** (`harness.yaml`) declares the models and the tasks. An **overlay** (`harness.<env>.yaml`) changes it per environment.
- `hw.load` validates everything at start-up. `harness.run` runs a task and returns a `RunResult`.
- Every run has a **trace** of the hook points it passed through. Controls attach to those hook points.
