# Models

The models module sends every model call through one `ModelProvider`, behind neutral contracts (`ModelRequest`, `ModelResponse`, `Message`, `ToolSpec`, `ToolCall`, `Usage`), so no SDK type ever reaches a hook or a contract (RULES R7). Apps ask for **aliases** (`fast`, `strong`), and the spec maps them to concrete models per environment.

```yaml
models:
  provider: openai.chat
  base_url: http://localhost:4000      # the gateway holds the keys (S1) and owns retries (R5)
  api_key_env: LITELLM_API_KEY
  default: fast
  aliases: { fast: fast-chat, strong: strong-chat }
  allowed_aliases: [fast, strong]      # usually set by the org baseline
  prices:
    fast-chat: { input_per_mtok: 0.15, output_per_mtok: 0.60 }
```

## Every call, governed

A model call made by a runner, by `s.generate(...)`, by an instrumented client or by an adapter goes through the same steps:

1. The alias is resolved (`request.alias`, else the task's `model`, else `models.default`) and checked against `models.allowed_aliases` (`model_not_allowed`).
2. The budget pre-check at `model.before`: call count, tokens and cost so far, and whether the estimated input fits ([Budgets](../concepts/envelope.md#budgets)).
3. `model.before` middleware, which may change the request (a redaction reaches the provider).
4. The provider call. With `stream: true`, each chunk fires `stream.chunk`, whose middleware can redact the chunk or cut the stream.
5. Usage and cost are recorded (a `harness.budget` note), and `model.after` middleware runs. A `Retry` there asks the model once more; after that, the run is blocked with `retry_exhausted`.
6. Going over `max_tokens` or `max_usd` after the call blocks the run.

A provider failure becomes a `ProviderError` (code `provider_error`, retryable).

## Aliases and environments

Overlays remap aliases, so code never names a concrete model:

```yaml
# harness.yaml
models: { provider: openai.chat, default: fast, aliases: { fast: fast-chat } }
# harness.prod.yaml
models: { aliases: { fast: fast-chat-prod } }
# harness.offline.yaml
models: { provider: scripted, replies: [{ text: "offline answer" }] }
```

Behind a LiteLLM gateway, the alias usually names a gateway model, and the gateway decides which provider model serves it (see [Gateways](../tooling/gateways.md)).

## Typed output

A task with an `output` type, or `s.generate(output=Model)`, asks the model for structured output (the provider sends the output schema as its API expects), parses the answer into the type, and hands failures to [validation](validation.md)'s bounded repair:

```python
class TicketSummary(BaseModel):
    category: Literal["billing", "bug", "account", "other"]
    priority: int = Field(ge=1, le=4)
    summary: str

summary = await s.generate(prompt="extract@1", output=TicketSummary, text=message)
```

## Cost

The cost of a call is the provider's report (such as LiteLLM's `x-litellm-response-cost` header), else `models.prices` by response model, request model or alias, else unknown, which is flagged on the trace and never guessed ([Cost](../concepts/envelope.md#cost)).

## Providers

### scripted

A deterministic model for tests and offline runs (RULES R14). Every example's offline overlay uses it. It ignores settings meant for a real provider (such as `base_url`), so an overlay can switch `provider: scripted` without repeating the section.

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
| `replies` | Used in order when no rule matches; when they run out, the last repeats unless `repeat_last: false` (then the call fails) |

A reply has `text`, `output` (structured output, also sent as JSON text), `tool_calls` (`{name, arguments, id}`), `usage` (default: estimated from the text), `cost_usd`, `model`, `chunks` (how to stream the text), `finish_reason`, and `fail: true` to raise a `ProviderError`. In tests, build one in code with `harnessweaver.testing.scripted(...)` ([Testing](../tooling/testing.md)).

### openai.chat

From `harnessweaver-openai`: Chat Completions on any OpenAI-compatible endpoint (LiteLLM Proxy, OpenAI, vLLM, Ollama).

| Setting | Default | Meaning |
| --- | --- | --- |
| `base_url` | the SDK's default | The endpoint, usually the gateway |
| `api_key_env` | `OPENAI_API_KEY` | The environment variable with the key; keys never go in the spec (S1) |
| `timeout` | `60s` | Per request |
| `max_retries` | `0` | SDK retries; the gateway retries (R5) |
| `max_tokens_param` | `max_tokens` | Or `max_completion_tokens` |
| `cost_header` | `x-litellm-response-cost` | The gateway's reported cost, used before `models.prices` |
| `default_headers` | none | Extra headers on every request |

Output schemas are sent as `response_format` (non-strict JSON Schema). Streaming includes usage.

### anthropic.messages

From `harnessweaver-anthropic`: the Claude Messages API, for teams without a gateway.

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
| `max_retries` | `2` | SDK retries; set `0` behind a gateway, which then owns retries (R5) |
| `cost_header` | `x-litellm-response-cost` | A gateway's reported cost, used before `models.prices` |
| `base_url`, `api_key_env` | SDK defaults | Client settings; credentials follow the SDK's own resolution unless `api_key_env` names a variable |

A request the model still declines after fallbacks ends the run `blocked` with code `model_refusal`. Each answer's content blocks, thinking included, are replayed unchanged on the next request of a tool loop, so reasoning carries over ([ADR-0022](../adr/0022-provider-extensions.md)).

## instrument()

Both plugins also govern a client the app already has:

```python
client = harness.instrument(AsyncOpenAI(base_url=GATEWAY))          # chat.completions.create
client = harness.instrument(AsyncAnthropic())                       # messages.create
```

Governed calls are traced, costed, budgeted and guarded (`input.before` on the message text, `output.before` on the answer), with redactions written back into the request and the answer. Other methods pass through. Streaming through an instrumented client is *planned* and raises for now. See [Integration styles](../concepts/integration-styles.md#wrap).

## Test mode

With `HARNESSWEAVER_TEST_MODE=1` (which `harnessweaver test` and the repository's test setup set), live providers refuse to call out, so a test can never spend tokens by accident. Record real answers once with a `Cassette` and replay them offline ([Testing](../tooling/testing.md#cassettes)).

## TypeScript

The TypeScript core has no model provider of its own: the app's Vercel AI SDK model is governed by `wrapModel(session, model, { alias })` from `@harnessweaver/ai-sdk`, with the same alias check, budgets, `model.before`, `model.after` and `stream.chunk` ([TypeScript](../tooling/typescript.md#models)).
