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

The spec calls a gateway, but you don't need one to try a real model: `models` can point at a provider directly. Pick yours, make the `models` section of `harness.yaml` match, and set the key it names.

=== "Gateway"

    Keep the spec as it is. Run [LiteLLM Proxy](https://docs.litellm.ai/docs/simple_proxy) on `localhost:4000` with a model it serves as `fast-chat`, or let `uv run harnessweaver dev harness.yaml --up` start one, with an OpenTelemetry collector and Langfuse (it needs Docker; see [the local dev stack](../deployment/gateways.md#the-local-dev-stack)). The gateway holds the provider keys, owns retries and fallbacks, and reports what each call cost. It is the setup for production.

    ```console
    $ export LITELLM_API_KEY=your-gateway-key
    ```

=== "OpenAI"

    ```yaml
    models:
      provider: openai.chat                  # no base_url: the OpenAI API itself
      api_key_env: OPENAI_API_KEY
      max_retries: 2                         # with no gateway, the SDK retries
      default: fast
      aliases: { fast: your-openai-model }   # a model id your account can use
    ```

    ```console
    $ export OPENAI_API_KEY=your-key
    ```

=== "Claude"

    Add the plugin for Claude first:

    ```console
    $ uv add "harnessweaver[anthropic]"
    ```

    ```yaml
    models:
      provider: anthropic.messages           # the key comes from ANTHROPIC_API_KEY, or `ant auth login`
      default: fast
      aliases: { fast: claude-haiku-5-5 }
    ```

    ```console
    $ export ANTHROPIC_API_KEY=your-key
    ```

=== "Ollama"

    A model running on your own machine with [Ollama](https://ollama.com): no key, no spend, nothing leaves the machine.

    ```yaml
    models:
      provider: openai.chat
      base_url: http://localhost:11434/v1    # Ollama's OpenAI-compatible API
      api_key_env: OLLAMA_API_KEY            # Ollama ignores the key, but one must be set
      default: fast
      aliases: { fast: your-local-model }    # one you pulled with `ollama pull`
    ```

    ```console
    $ export OLLAMA_API_KEY=ollama
    ```

Then run without the overlay:

```console
$ uv run python main.py
```

!!! tip "If it prints `failed`"
    `result.error` says why. Print `result.error.message`: `openai.chat needs $OPENAI_API_KEY` means the variable isn't set, and `openai.chat: APIConnectionError` means nothing answered at `base_url`. [Troubleshooting](../how-to/troubleshooting.md#when-a-run-fails) lists the rest.

A provider called directly doesn't report what a call cost, so the cost is marked unknown until you give prices ([Models and environments](models.md#cost) shows how). The rest of the tutorial keeps running offline, so you can follow it without a gateway or a key.

## Recap

- A **spec** (`harness.yaml`) declares the models and the tasks. An **overlay** (`harness.<env>.yaml`) changes it per environment.
- `hw.load` validates everything at start-up. `harness.run` runs a task and returns a `RunResult`.
- Every run has a **trace** of the hook points it passed through. Controls attach to those hook points.
