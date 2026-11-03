# Observability

Every decision HarnessWeaver makes is a traced event (RULES R13): each guard that fired, each budget check, each route chosen, each tool allowed or denied, each repair. You've been reading traces since [First steps](first-steps.md). This chapter reads one closely, then sends the same events to OpenTelemetry in production, without any prompts, outputs or tool arguments in them.

## Read a trace

Triage a message that holds an e-mail address, now that the org baseline and the extraction profile are in place:

```python title="main.py"
--8<-- "docs_src/tutorial/observability/main.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed, cost $0.000076 (known: True)
   0 hook    run.start         harness -> continue
   1 note    -                 harness.guard (guard_fired): guardrails.input[base-pii] redact
   2 outcome input.before      guardrails.input[base-pii] [baseline] -> continue: guardrails.input[base-pii]: found EMAIL
   3 outcome input.before      guardrails.input[extraction-pii] [platform] -> continue
   4 outcome input.before      guardrails.input[injection] [app] -> continue
   5 hook    input.before      harness -> continue: guardrails.input[base-pii]: found EMAIL
   6 hook    model.before      harness -> continue
   7 note    model.after       harness.budget: model usage
   8 hook    model.after       harness -> continue
   9 outcome output.before     guardrails.output[base-secrets] [baseline] -> continue
  10 outcome output.before     guardrails.output[extraction-secrets] [platform] -> continue
  11 outcome output.before     validation.rules[bugs-are-urgent] [app] -> continue
  12 outcome output.before     validation.rules[short-summary] [app] -> continue
  13 hook    output.before     harness -> continue
  14 hook    run.end           harness -> continue
```

Read it top to bottom. The baseline's PII guard found an e-mail address and redacted it (events 1 and 2), then the profile's PII guard and your injection guard found nothing more. The model saw only `[EMAIL]`. Its usage was recorded (event 7), then the output passed the baseline's and the profile's secrets checks and your two rules, each in its band.

Each event has a `kind`:

| Kind | Records |
| --- | --- |
| `hook` | A hook point fired, with the combined outcome of its middleware |
| `outcome` | One middleware's answer, with its band |
| `failure` | A middleware raised or timed out (its exception type, never its message) |
| `note` | A framework decision: a guard fired, a budget check, a route, a governor step, a repair |

The trace holds ids, codes, names and numbers, never content (RULES R9). It powers `assert_trace` in [tests](testing.md), the `guard_fired` grader and the shadow-guard report in [evals](evals.md), and the comparison in [replay](state.md#replay-a-run).

## Send it to OpenTelemetry

The core uses only the OpenTelemetry **API**. If your app already sets up OpenTelemetry, do nothing: the harness's spans join your traces. If it doesn't, install `harnessweaver-otel` and let the harness set it up. That belongs in production's overlay:

```yaml title="harness.prod.yaml"
--8<-- "docs_src/tutorial/observability/harness.prod.yaml"
```

| Setting | Meaning |
| --- | --- |
| `configure_sdk` | Let `otel.sdk` install the SDK's tracer and meter providers, once, when the harness loads |
| `exporter` | `none`, `console` or `otlp` |
| `endpoint` | The OTLP endpoint. The standard `OTEL_EXPORTER_OTLP_*` variables are read too |
| `service_name` | The service name on telemetry. The default is `metadata.name` |
| `capture_content` | `false` (the default). Org baselines usually lock it |

If the app already installed SDK providers, `otel.sdk` changes nothing, because telemetry setup has one owner (RULES R5). In test mode the OTLP exporter isn't installed (R14).

### Spans

| Span | For |
| --- | --- |
| `harness.run` | One run or session |
| `chat {model}` | A model call, following the GenAI semantic conventions |
| `execute_tool {tool}` | A tool call |
| `invoke_agent {agent}`, `invoke_workflow {name}` | Agent adapters and workflows |
| `harness.decision`, `harness.guard`, `harness.approval` | A routing decision, a guard that fired, an approval |

Spans carry the GenAI attributes (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, ...) pinned to semantic conventions 1.42.0, and HarnessWeaver's own (`harness.run.id`, `harness.task`, `harness.tenant`, `harness.cost.usd`, ...). The metrics are `gen_ai.client.token.usage`, `gen_ai.client.operation.duration` and `harness.cost`.

### Content

With `capture_content: false`, prompts, outputs, tool arguments and tool results never reach a span. When a spec turns it on, they are captured **after** the `model.before`, `model.after`, `tool.before` and `tool.after` middleware, so every redaction applies first (RULES R9).

!!! tip
    `uv run harnessweaver dev harness.yaml --up` starts a local stack with an OpenTelemetry collector that forwards traces to Langfuse, so you can see spans while you develop ([Gateways and the dev stack](../deployment/gateways.md#the-local-dev-stack)).

## Logs

HarnessWeaver logs through [loguru](https://loguru.readthedocs.io/) and is silent until your app turns it on:

```python
from loguru import logger

logger.enable("harnessweaver")              # the core
logger.enable("harnessweaver_openai")       # one plugin
```

The library never adds a log sink, so where logs go stays your choice. Logs carry ids and error types, never content.

## Recap

- Every run's **trace** records every hook, middleware outcome and decision, without content.
- The same events become OpenTelemetry spans and metrics. Set up the SDK yourself, or let `harnessweaver-otel` do it from the spec.
- Content stays out of telemetry unless the spec captures it, and then only after redaction.
