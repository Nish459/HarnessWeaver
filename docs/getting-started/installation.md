# Installation

HarnessWeaver is a set of packages: a small Python core, a CLI, a sidecar, plugins, and a TypeScript core with an AI SDK adapter. You install the core and only the plugins your spec uses. Installing a plugin enables nothing on its own: only the names your `harness.yaml` refers to are imported (RULES S8).

!!! warning "Not published yet"
    0.1.0 is in preparation and the packages aren't on PyPI or npm yet. Until then, install from a clone of the repository ([From source](#from-source)). The [package commands](#once-the-packages-are-published) below are what you will use after the release.

## Requirements

| For | You need |
| --- | --- |
| Python apps, the CLI and the sidecar | Python 3.12 or later (the repository develops on 3.14), and [uv](https://docs.astral.sh/uv/) |
| TypeScript apps | Node 22 or later, and [pnpm](https://pnpm.io/) for working on the repository |
| The local dev stack (`harnessweaver dev --up`) and the sidecar image | Docker with Compose |
| The docs site (`make docs`) | Nothing extra: the `docs` dependency group of the uv workspace |

## From source

```bash
git clone https://github.com/Wise-DreamerZ/HarnessWeaver.git
cd HarnessWeaver
uv sync --all-packages            # every Python package plus the development tools, into .venv
```

Check it:

```bash
uv run harnessweaver --version
HARNESSWEAVER_ENV=offline uv run python examples/01_invoice_extraction/run.py
```

Run your own project with this installation by pointing `uv run` at the clone, from your project's directory:

```bash
cd ../my-app
HARNESSWEAVER_ENV=offline uv run --project ../HarnessWeaver python -m app.main
```

CLI commands that take a spec accept a path, so they can run from the clone: `uv run harnessweaver spec validate ../my-app/harness.yaml`.

Or give the project its own environment that uses the clone: point each HarnessWeaver package it depends on at the clone with a path source in its `pyproject.toml`. A project from `harnessweaver init` depends on `harnessweaver[openai]` (the `agent` template on `pydantic-ai` too) and has `harnessweaver-cli` as a dev dependency, so:

```toml
[tool.uv.sources]
harnessweaver = { path = "../HarnessWeaver/python/harnessweaver", editable = true }
harnessweaver-openai = { path = "../HarnessWeaver/python/plugins/openai", editable = true }
harnessweaver-cli = { path = "../HarnessWeaver/python/harnessweaver-cli", editable = true }
# the agent template also needs:
# harnessweaver-pydantic-ai = { path = "../HarnessWeaver/python/plugins/pydantic-ai", editable = true }
```

Then `uv run harnessweaver test` and `uv run python -m app.main` inside the project work as they will after the release. Remove the sources once the packages are published.

For TypeScript, install and build the pnpm workspace:

```bash
pnpm -C typescript install
pnpm -C typescript build          # @harnessweaver/core and @harnessweaver/ai-sdk into their dist/ folders
```

[Example 04](examples.md#example-04-one-spec-every-language) is a TypeScript app inside that workspace, and the template for using the packages from source.

## Once the packages are published

### Python

```bash
uv add harnessweaver                     # the core: pydantic, opentelemetry-api, pyyaml, anyio, loguru
uv add "harnessweaver[openai]"           # plus one first-party plugin
uv add --dev harnessweaver-cli           # the harnessweaver command
uv add "harnessweaver[all]"              # every first-party plugin, the CLI and the sidecar
```

| Package | Extra | What it adds |
| --- | --- | --- |
| `harnessweaver` | - | The core: spec loader, hook bus, envelope and budgets, runners, the built-in modules, the test kit. `import harnessweaver as hw` |
| `harnessweaver-cli` | `cli` | The `harnessweaver` command ([CLI](../tooling/cli.md)) |
| `harnessweaver-sidecar` | `sidecar` | `harnessd`, the HTTP sidecar ([harnessd](../tooling/sidecar.md)) |
| `harnessweaver-openai` | `openai` | `openai.chat`, for any OpenAI-compatible endpoint (LiteLLM Proxy, OpenAI, vLLM, Ollama), and `instrument()` for OpenAI clients |
| `harnessweaver-anthropic` | `anthropic` | `anthropic.messages` for Claude, and `instrument()` for Anthropic clients |
| `harnessweaver-pydantic-ai` | `pydantic-ai` | The `pydantic_ai.agent` runner and `wrap()` for Pydantic AI agents |
| `harnessweaver-monty` | `monty` | `monty.sandbox`, which runs code-executing tools away from the host process |
| `harnessweaver-otel` | `otel` | `otel.sdk`, which sets up the OpenTelemetry SDK and an exporter |
| `harnessweaver-cel` | `cel` | `cel.policy`, full CEL for policy rules |

An extra only installs the package. Your spec still decides what is used, and an org baseline can restrict which plugins apps may use (`plugins.allow`).

### TypeScript

```bash
npm install @harnessweaver/core                          # the TypeScript core
npm install @harnessweaver/ai-sdk ai @ai-sdk/provider     # plus wrapModel for the Vercel AI SDK (v7)
```

See [TypeScript](../tooling/typescript.md).

### The sidecar image

```bash
docker build -f deploy/harnessd/Dockerfile -t harnessd .
```

See [harnessd](../tooling/sidecar.md#the-container).

## Logging

HarnessWeaver logs through [loguru](https://loguru.readthedocs.io/) and is silent until you turn it on:

```python
from loguru import logger

logger.enable("harnessweaver")              # the core
logger.enable("harnessweaver_openai")       # a plugin's own logs
```

The library never adds a log sink, so where logs go stays your choice. Logs carry ids and error types, never prompts, outputs or tool arguments (RULES R9). See [Observability](../modules/observability.md#logs).

## Next

- [Quickstart](quickstart.md): your first governed task.
- [Examples](examples.md): four apps that show each part of the framework.
