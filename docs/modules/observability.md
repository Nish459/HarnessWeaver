# Observability

Every decision HarnessWeaver makes is a traced event (RULES R13). Each run keeps a framework-neutral **trace** on its result, and the same events become **OpenTelemetry** spans and metrics, following the GenAI semantic conventions. Content (prompts, outputs, tool arguments) stays out of telemetry unless the spec turns capture on, and then only after redaction (R9).

```yaml
observability:
  configure_sdk: true                  # let harnessweaver-otel set up the SDK
  exporter: otlp                       # none | console | otlp
  endpoint: http://otel-collector:4318
  service_name: invoice-extractor      # default: metadata.name
  capture_content: false               # the default; usually locked by the baseline
```

## The trace

Every `RunResult` carries its `trace`: one event per middleware outcome, one per hook point that fired, and notes for framework decisions (guards that fired, budget checks, routing, governor steps, repairs, context drops). See [the trace](../concepts/lifecycle.md#the-trace).

```python
from harnessweaver.testing import render_trace

print(render_trace(result))      # one event per line
```

The trace powers `assert_trace` in tests, the `guard_fired` grader, the shadow-guard report, and the decision comparison of `harnessweaver replay`. It holds ids, codes, names and numbers, never content.

## Spans

The core uses only the OpenTelemetry **API** ([ADR-0010](../adr/0010-otel-api-only.md)). Its spans and metrics go wherever the app's own SDK setup sends them; without an SDK they cost almost nothing.

| Span | For |
| --- | --- |
| `harness.run` | One run or session |
| `chat {model}` | A model call (GenAI convention) |
| `execute_tool {tool}` | A tool call (GenAI convention) |
| `invoke_agent {agent}`, `invoke_workflow {name}` | Agent adapters and workflows |
| `harness.decision` | A routing decision |
| `harness.guard` | A guard that fired |
| `harness.approval` | An approval request or answer |

Middleware outcomes other than `Continue`, and middleware failures, are added to the current span as `harness.outcome` events. Spans record an error's type (`error.type`), never its message.

### Attributes

| Namespace | Attributes |
| --- | --- |
| GenAI | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.tool.name` |
| HarnessWeaver | `harness.run.id`, `harness.task`, `harness.tenant`, `harness.hook`, `harness.outcome`, `harness.band`, `harness.cost.usd`, `harness.decision.*`, `harness.guard.*` |

The GenAI names are pinned to semantic conventions **1.42.0** (`SEMCONV_VERSION`). In 1.42.0 the GenAI conventions moved to their own repository and are still marked Development, so a test compares the names with the installed `opentelemetry-semantic-conventions` package to catch drift.

### Metrics

| Metric | Meaning |
| --- | --- |
| `gen_ai.client.token.usage` | Tokens per call, by type |
| `gen_ai.client.operation.duration` | Call duration |
| `harness.cost` | USD, for calls whose cost is known |

## Content capture

`capture_content: false` is the default (R9), and org baselines usually lock it. When it is on, `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.tool.call.arguments` and `gen_ai.tool.call.result` hold the content **after** the `model.before`, `model.after`, `tool.before` and `tool.after` middleware, so redactions apply first.

## Setting up the SDK

If your app already configures OpenTelemetry, do nothing: HarnessWeaver's spans join your traces. If it doesn't, install `harnessweaver-otel` and let the harness configure it:

| Setting | Default | Meaning |
| --- | --- | --- |
| `configure_sdk` | `false` | Let `otel.sdk` install SDK tracer and meter providers, once, when the harness loads |
| `exporter` | `none` | `console` or `otlp`; an exporter without `configure_sdk: true` is a load error |
| `endpoint` | none | The OTLP endpoint; the standard `OTEL_EXPORTER_OTLP_*` variables are also read |
| `service_name` | `metadata.name` | The service name |
| `export_interval` | `60s` | How often metrics are exported |

If the app already installed SDK providers, `otel.sdk` changes nothing: telemetry setup has one owner (RULES R5). In test mode the OTLP exporter isn't installed (R14).

`harnessweaver dev` writes a local stack with an OpenTelemetry collector that forwards traces to Langfuse ([Gateways and the dev stack](../tooling/gateways.md#the-local-dev-stack)).

## Logs

HarnessWeaver logs through [loguru](https://loguru.readthedocs.io/) and is silent until the app turns it on ([ADR-0024](../adr/0024-loguru.md)):

```python
from loguru import logger

logger.enable("harnessweaver")              # the core
logger.enable("harnessweaver_openai")       # one plugin's logs
```

The library never adds a sink, so where logs go is the app's choice. An app on the standard `logging` module can add a loguru sink that forwards each record to it. Logs carry ids and error types, never content; the conformance suite checks loguru and `logging` output alike for leaks.

## TypeScript

`@harnessweaver/core` keeps the same trace on every `RunResult` (pass `onEnd` to `harness.session`). OpenTelemetry export from TypeScript is *planned*.
