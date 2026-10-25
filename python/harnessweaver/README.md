# harnessweaver

The core of [HarnessWeaver](https://github.com/Wise-DreamerZ/HarnessWeaver), *the composable AI harness framework*: the spec loader, the 13-point hook bus, envelope and budgets, the error taxonomy, the runners, the built-in modules and the test kit. It depends only on `pydantic`, `opentelemetry-api`, `pyyaml`, `anyio` and `loguru`.

```bash
uv add harnessweaver                 # the core
uv add "harnessweaver[openai]"       # plus a first-party plugin
uv add "harnessweaver[all]"          # every first-party plugin, the CLI and the sidecar
```

> Pre-release: the package isn't published yet; install from a clone of the repository ([QUICKSTART](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/QUICKSTART.md)).

```python
import harnessweaver as hw

harness = hw.load("harness.yaml")        # spec + org baseline + env overlay, validated at startup

# Wrap: govern a client the app already has
client = harness.instrument(AsyncOpenAI(base_url=GATEWAY))

# Session: your code owns the flow, the harness governs each step
async with harness.session("support", principal=user, tenant="acme") as s:
    route = await s.decide("intent", text=question)
    articles = await s.context("help").fetch(question)
    answer = await s.generate(prompt="answer@1", question=question, intent=route.choice)

# Run: the harness owns the lifecycle
result = await harness.run("extract_invoice", doc, principal=user)
```

| Extra | Adds |
| --- | --- |
| `openai` | `openai.chat` for any OpenAI-compatible endpoint, and `instrument()` for OpenAI clients |
| `anthropic` | `anthropic.messages` for Claude, and `instrument()` for Anthropic clients |
| `pydantic-ai` | The `pydantic_ai.agent` runner and `wrap()` for Pydantic AI agents |
| `monty` | `monty.sandbox` for code-executing tools |
| `otel` | `otel.sdk`: OpenTelemetry SDK and exporter setup |
| `cel` | `cel.policy`: full CEL for policy rules |
| `cli` | The `harnessweaver` command |
| `sidecar` | `harnessd`, the HTTP sidecar |
| `all` | All of the above |

The test kit is `harnessweaver.testing`, and installing the package adds the plugin conformance suite to pytest (`pytest --harnessweaver-conformance=<namespace>`).

Documentation: [the docs](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/index.md), from [Concepts](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/concepts/index.md) to the [spec reference](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/spec/reference.md).
