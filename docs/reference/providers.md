# Providers

Every built-in and first-party provider, with its settings. A provider is chosen with `use:` (or `provider:` in `models`), and its settings sit next to that key. They are validated against the provider's config model when the harness loads, so a misspelled setting fails (RULES R4).

Every provider declares whether it is **deterministic**. Probabilistic components may route a decision or make it stricter, never grant anything (RULES R3).

| Deterministic | Probabilistic |
| --- | --- |
| `pii.regex`, `secrets.scan`, `injection.heuristic`, `regex.deny`, `size.limit`, `topic.deny`, `grounded.citations`, `cel_lite`, `rules`, `lexical`, `semantic` (with the hashing embedder), the deterministic graders | `llm.judge`, the `llm` routing stage, the `llm_judge` grader |

## Models

The `models` section picks one provider with `provider:` ([Models and environments](../tutorial/models.md)).

### scripted

A deterministic model for tests and offline runs (RULES R14). It ignores settings meant for a real provider (such as `base_url`), so an overlay can switch to it without repeating the section.

```yaml
models:
  provider: scripted
  rules:                                    # checked first, against the last message
    - { contains: "refund", reply: { tool_calls: [{ name: refund, arguments: { amount: 5 } }] } }
    - { role: tool, reply: { text: "Refund done." } }
  replies:                                  # then used in order
    - { output: { vendor: "ACME", total: 12.5 } }
  repeat_last: true
```

| Setting | Meaning |
| --- | --- |
| `rules` | Each has a `reply` and matchers on the **last message**: `contains` (case-insensitive), `matches` (a regex), `role`; and `times`, after which it stops matching |
| `replies` | Used in order when no rule matches. When they run out, the last repeats, unless `repeat_last: false` (then the call fails) |

A reply has `text`, `output` (structured output, also sent as JSON text), `tool_calls` (`{name, arguments, id}`), `usage` (default: estimated from the text, one token per four characters), `cost_usd`, `model`, `chunks` (how to stream the text), `finish_reason`, and `fail: true` to raise a `ProviderError`. In tests, build one with `harnessweaver.testing.scripted(...)` ([Testing](../tutorial/testing.md#scripted-models)).

### openai.chat

From `harnessweaver-openai`: Chat Completions on any OpenAI-compatible endpoint (LiteLLM Proxy, OpenAI, vLLM, Ollama).

| Setting | Default | Meaning |
| --- | --- | --- |
| `base_url` | the SDK's default | The endpoint, usually the gateway |
| `api_key_env` | `OPENAI_API_KEY` | The environment variable with the key. Keys never go in the spec (S1) |
| `timeout` | `60s` | Per request |
| `max_retries` | `0` | SDK retries. The gateway retries (R5) |
| `max_tokens_param` | `max_tokens` | Or `max_completion_tokens` |
| `cost_header` | `x-litellm-response-cost` | The gateway's reported cost, used before `models.prices` |
| `default_headers` | none | Extra headers on every request |
| `hold_stream` | `false` | Deliver a streamed answer's chunks only once it has finished, so nothing from a declined answer reaches the app. Output is no longer live |
| `block_empty_answers` | `false` | Treat an answer with no text and no tool calls as declined |

Output schemas are sent as `response_format` (non-strict JSON Schema). Streaming includes usage.

A request the model declines ends the run `blocked` with the code `model_refusal`, and its tokens and cost still count. It is recognized by the message's `refusal` field (LiteLLM moves it to `provider_specific_fields`, which is also read) or the finish reason `content_filter`, which is how LiteLLM reports a Claude refusal. So an answer a content filter cut short ends the same way, and its partial text is dropped.

Three cases need a setting, because the signal is late or missing:

| Case | What happens by default | What to set |
| --- | --- | --- |
| The signal arrives after text has been streamed | The run ends blocked, but those chunks have already been delivered | `hold_stream: true` |
| A streamed refusal through LiteLLM, which drops the field (seen on 1.106.6) | An empty answer that completes normally | `block_empty_answers: true`. Off by default, because a model may also end a tool loop with nothing to add |
| An endpoint that sends a refusal as ordinary text | An answer like any other | A `regex.deny` output guard on the wording you see. It starts in shadow mode (RULES R8) and ends the run with the code `guard_blocked`. Guards don't run on empty text |

```yaml
guardrails:
  output:
    - id: refusal-text
      use: regex.deny
      patterns: ["^i'm sorry, but i can't"]
      ignore_case: true
      mode: log_only
```

### anthropic.messages

From `harnessweaver-anthropic`: the Claude Messages API, called directly or through a gateway that serves it.

```yaml
models:
  provider: anthropic.messages
  default: strong
  aliases: { strong: claude-opus-5-5, fast: claude-haiku-5-5 }
  effort: high
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `model` | `claude-opus-5-5` | When a request names no model |
| `max_tokens` / `stream_max_tokens` | `16000` / `64000` | When a request sets none |
| `thinking` | `adaptive` | Or `none` to omit the parameter |
| `effort` | the model's default | `low`, `medium`, `high`, `xhigh`, `max` |
| `fallbacks` | `default` | Server-side refusal fallbacks; `none` turns them off |
| `structured_outputs` | `false` | Send output schemas as the API's structured output format (they must meet its rules); otherwise the schema goes in the system prompt |
| `sampling` | `false` | Forward `temperature` (older models only); current models reject sampling parameters |
| `timeout` | `600s` | Per request |
| `max_retries` | `2` | SDK retries. Set `0` behind a gateway, which then owns retries (R5) |
| `cost_header` | `x-litellm-response-cost` | A gateway's reported cost, used before `models.prices` |
| `base_url`, `api_key_env` | SDK defaults | Client settings. Credentials follow the SDK's own resolution (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, an `ant auth login` profile, workload identity) unless `api_key_env` names a variable. When none is found, a call fails with a `provider_error` that says what to set |
| `hold_stream` | `false` | Deliver a streamed answer's chunks only once it has finished, so nothing from a declined answer reaches the app. Output is no longer live |

A request the model still declines after fallbacks ends the run `blocked` with the code `model_refusal`, and its tokens still count. Each answer's content blocks, thinking included, are replayed unchanged on the next request of a tool loop, so reasoning carries over.

### Choosing a model provider

`openai.chat` is the one route to every model: point it at a gateway, and the gateway reaches the rest, Claude included. But it speaks only Chat Completions, so what that API doesn't carry is lost. To use what is specific to Claude, use `anthropic.messages`.

| | `openai.chat` | `anthropic.messages` |
| --- | --- | --- |
| Reaches | Any model behind an OpenAI-compatible endpoint | Claude, directly or through a gateway that serves the Messages API |
| Thinking | Not requested, and not replayed between turns | Adaptive, and replayed between turns of a tool loop |
| `effort`, `thinking`, `fallbacks` | Not settings of this provider: naming one fails loading (RULES R4) | Settings of this provider |
| A request the model declines | The run ends `blocked` with the code `model_refusal`, with no fallback and no category. Through LiteLLM it can't be told apart from a content filter | Re-run on the fallback model, then the run ends `blocked` with the code `model_refusal` and the refusal's `category` |
| `temperature` | Sent when a request sets it | Sent only with `sampling: true` |
| SDK retries by default | `0`: the gateway owns them (RULES R5) | `2`: set `0` behind a gateway |

Behind a gateway, `anthropic.messages` takes `base_url` and `max_retries: 0`, and `fallbacks: none` if the gateway rejects beta parameters.

`harness.instrument()` is a separate choice. It picks its adapter from the client the app passes, not from `models.provider`, so each SDK needs its own plugin ([Govern an existing client](../how-to/wrap-a-client.md#what-instrument-does)).

## Guards

Guards are listed per stage under `guardrails` ([Guardrails](../tutorial/guardrails.md)). These are each guard's own settings. The keys every guard shares (`id`, `use`, `action`, `mode`, `where`, `parallel`, `fail_mode`, `timeout`, `enabled`) are in the [section reference](spec.md#guardrails). The built-in patterns are part of the contract, in regex syntax Python and TypeScript share.

### pii.regex

Finds e-mail addresses, phone numbers, card numbers (Luhn-checked), US social security numbers and IP addresses, and redacts them. Its findings are marked **private**, so a run where it finds PII is marked private wherever the guard runs (the trifecta check reads this).

| Setting | Default | Meaning |
| --- | --- | --- |
| `entities` | all | Any of `EMAIL`, `CREDIT_CARD`, `SSN`, `PHONE`, `IP_ADDRESS` |
| `replacement` | `[{entity}]` | `{entity}` is replaced by the entity name, so `ann@example.com` becomes `[EMAIL]` |

Proposes `redact`. Stages: all.

### secrets.scan

Finds credentials: private keys, AWS access keys, GitHub, Slack, Anthropic and OpenAI keys, Google API keys, JWTs, and credential assignments such as `password=...`.

| Setting | Default | Meaning |
| --- | --- | --- |
| `kinds` | all | Any of `private_key`, `aws_access_key`, `github_token`, `slack_token`, `anthropic_key`, `openai_key`, `google_api_key`, `jwt`, `credential_assignment` |
| `replacement` | `[SECRET]` | Used with `action: redact` |

Proposes `block`. Stages: all.

### injection.heuristic

Scores phrases typical of prompt injection (`ignore previous instructions`, requests to reveal the system prompt, role overrides, fake system messages, exfiltration requests) and flags content whose score reaches the threshold. It is cheap and **easy to evade**: pair it with the trifecta check, untrusted labels and approvals, and add a model-based detector when the stakes need one.

| Setting | Default | Meaning |
| --- | --- | --- |
| `threshold` | `0.5` | The score that flags content |

Proposes `block`. Stages: `input`, `context`, `tool_result`.

### regex.deny

Flags content matching any of your patterns.

| Setting | Default | Meaning |
| --- | --- | --- |
| `patterns` | required | Regular expressions (the syntax Python and JavaScript share) |
| `ignore_case` | `false` | Match regardless of case |
| `replacement` | `[REDACTED]` | Used with `action: redact` |

Proposes `block`. Stages: all.

### size.limit

Flags content over a size. Its redaction truncates.

| Setting | Default | Meaning |
| --- | --- | --- |
| `max_chars` | none | Characters (code points) |
| `max_bytes` | none | UTF-8 bytes |

Proposes `block`. Stages: all.

### topic.deny

Flags content that mentions denied topics, by whole-word keywords, ignoring case.

| Setting | Default | Meaning |
| --- | --- | --- |
| `topics` | required | A map of topic name to keywords: `{legal: [lawsuit, attorney]}` |
| `replacement` | `[REDACTED]` | Used with `action: redact` |

Proposes `block`. Stages: `input`, `output`.

### grounded.citations

Checks that the output's sentences (ending at `.`, `!` or `?` and a space, or a line break) of at least `min_words` words cite a context item in square brackets, like `[help-refunds]`, and that each citation names an item the run actually retrieved. Proposes `repair` (the model is asked to cite). Set `action: escalate` to send uncited answers to a person instead.

| Setting | Default | Meaning |
| --- | --- | --- |
| `min_supported` | `0.9` | The share of sentences that must cite |
| `min_words` | `4` | Shorter sentences need no citation |
| `require_known` | `true` | Citations must name items the run kept |
| `pattern` | `\[([A-Za-z0-9_.:#/-]+)\]` | How a citation looks; group 1 is the item id |

Stages: `output`.

### llm.judge

Asks a model whether the content meets your criteria. The call is governed and budgeted like any other model call, and the judge's own explanation isn't kept (R9). It is probabilistic, so it can only make a decision stricter (R3).

| Setting | Default | Meaning |
| --- | --- | --- |
| `criteria` | required | What acceptable content looks like |
| `model` | `models.default` | The model alias for the judge |

Proposes `block` when the content fails. Stages: `input`, `output`.

## Routing stages

Stages of a router's `cascade` ([Routing](../tutorial/routing.md)). Every stage also takes `id` and `threshold` ([section reference](spec.md#routing)).

| Stage | Settings |
| --- | --- |
| `rules` | `rules`: a list of `{when, choice}`; `when` sees `text`, `state`, `options` and `router`. Or `file`: a YAML file with a `rules` list, relative to the spec. A rule that can't be evaluated doesn't match |
| `lexical` | `utterances`: a map of option to example texts, or `file`: a YAML file with an `utterances` map. Each option scores its closest example by the cosine of token counts; ties go to the option listed first; a text that shares no token with any example abstains |
| `semantic` | `utterances` or `file`, as for `lexical`, and `encoder` (default `semantic.hashing`, an `Embedder` provider). `semantic.hashing` hashes words and character trigrams (32-bit FNV-1a) into a vector of `dims` (default 256): dependency-free and deterministic |
| `llm` | `model` (default `models.default`) and `instructions`. Asks the model to pick an option with a confidence; the call is governed and budgeted, and the explanation isn't kept. The confidence is uncalibrated: tune the threshold on labelled examples |

## Context sources

Sources under `context` ([Retrieval and memory](../tutorial/context.md)). Every source also takes `label`, `max_items`, `max_tokens` and `require_acl` ([section reference](spec.md#context)).

| Provider | What it does | Settings |
| --- | --- | --- |
| `memory` | Documents held in memory, searched lexically (token cosine) | `documents`: a list of `{id, content, acl, metadata}`; or `file`: a YAML file with a `documents` list, relative to the spec |
| `passthrough` | Fetches nothing; governs the items your code passes to `s.context(name).check(items)` | none |

The `memory` section's store (`use: memory`) keeps key-value entries in the process, namespaced by tenant, principal and task. Vector stores and search services (pgvector, OpenSearch, Qdrant) are *planned* as plugins.

## Approval channels

The channel `approvals.use` names is notified of each request once it and the run's checkpoint are saved ([Approvals](../tutorial/approvals.md)).

| Channel | Does | Settings |
| --- | --- | --- |
| `memory` | Keeps every request (the default), for tests and apps that poll | none |
| `callback` | Calls your function, sync or async, with each `ApprovalRequest`. It must not answer in-line | `handler`: `package.module:function` |
| `console` | Writes one line per request, for local development | `stream`: `stderr` (default) or `stdout` |
| `webhook` | POSTs each request as JSON | `url`; `timeout` (default `10s`); `headers_env`: header name to environment variable (S1). Refuses the network in test mode |
| `email` | Sends each request by e-mail via SMTP (standard library only) | `host`: SMTP host (required); `sender`: From address (required); `recipients`: list of To addresses (required, at least one); `port` (default `587`, range 1-65535); `starttls` (default `true`, uses verified TLS via `ssl.create_default_context`); `timeout` (default `30s`); `login_env` (default `HARNESSWEAVER_EMAIL_LOGIN`), `password_env` (default `HARNESSWEAVER_EMAIL_PASSWORD`): environment variables for SMTP credentials (S1); set both to `null` for unauthenticated relays. Refuses the network in test mode |

A channel that fails is traced (`approval_notify_failed`) and the run keeps waiting: the request is already saved. Slack and an approval page are *planned*.

## State stores

| Store | Keeps | Settings |
| --- | --- | --- |
| `memory` | Everything in the process (the default) | none |
| `sqlite` | Everything in a SQLite file | `path`: default `.harness/state.db`, relative to the working directory; `:memory:` keeps it in memory |

Any `StateStore` provider works, and the conformance suite checks it with a round-trip contract, including that only one answer can claim a pending approval. Postgres and Redis stores are *planned*.

## Policy engines

| Engine | From | Notes |
| --- | --- | --- |
| `cel_lite` | The core | The default; the same in Python and TypeScript |
| `cel.policy` | `harnessweaver-cel` | Full CEL through cel-python. It doesn't mix ints and doubles (`1 + 0.5` is an error), and such an error makes the rule unevaluable, so `deny` and `require_approval` rules still apply |

Both pass the shared `governor` fixtures. Any `PolicyEngine` provider must declare `deterministic=True`, or loading fails (R3).

## Graders

Graders in eval datasets ([Evals](../tutorial/evals.md)). A grader is written as its name (`schema_valid`) or as `{name: settings}`, and a single value fills its main setting: `{field_equals: intent}` is `{field_equals: {field: intent}}`. The deterministic ones score 1 or 0 and behave identically in Python and TypeScript (fixtures suite `evals`).

| Grader | Main setting | Other settings | Passes when |
| --- | --- | --- | --- |
| `exact` | - | - | The output equals `expect` (JSON equality: numbers by value, maps in any order, never a boolean as a number) |
| `field_equals` | `field` | - | The output's `field` (a dotted path such as `line_items.1.amount`) equals the same field of `expect` |
| `numeric_close` | `field` | `tolerance` (default `1e-6`) | The number at `field` (or the whole output) is within `tolerance` of `expect`'s |
| `contains` | `text` (one or a list) | `ignore_case` | The output's text contains every listed text |
| `regex` | `pattern` | - | The pattern matches somewhere in the output's text |
| `citation_present` | `ids` (one or a list) | `pattern` | The output cites every listed id (`[kb-1]`), or something, when no ids are listed |
| `schema_valid` | - | - | The run completed and its output matches the task's output schema |
| `guard_fired` | `guard` (ids or full names) | `fired` (default true), `action` | Each listed guard fired in the run, or would have in shadow mode; `fired: false` for cases that must stay quiet |
| `status` | `status` (one or a list) | - | The run ended with one of the listed statuses |
| `llm_judge` | `rubric` | `model`, `threshold` (default `0.5`) | A model scores the output from 0 to 1 against the rubric, given the input, at or above `threshold` |

"The output's text" is the output itself when it is a string, and otherwise its canonical JSON: sorted keys, no spaces, non-ASCII kept, integral numbers without a fraction. In results, each grader is labelled `name`, `name:value` (for a text, number or boolean setting) or `name#n` (for a list or map setting). `llm_judge` grades inside a session, so its calls are governed and budgeted, and its reason isn't kept (R9). A grader that raises fails its case, not the suite.

## Sandboxes

| Sandbox | From | Runs |
| --- | --- | --- |
| `monty.sandbox` (`monty` for short) | `harnessweaver-monty` | Code-executing tools (`transport: code`) away from the host process, with no host files, network or environment, a fresh worker per call ([The tool governor](../advanced/governor.md#sandboxed-code)) |

## Telemetry

| Provider | From | Does |
| --- | --- | --- |
| `otel.sdk` | `harnessweaver-otel` | Installs the OpenTelemetry SDK and an exporter when `observability.configure_sdk` is true ([Observability](../tutorial/observability.md#send-it-to-opentelemetry)) |
