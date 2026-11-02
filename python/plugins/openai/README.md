# harnessweaver-openai

A first-party [HarnessWeaver](../../../README.md) plugin for OpenAI-compatible models. It is built on the same plugin contract any third-party plugin uses: one `hw.Plugin` object, published through the `harnessweaver.plugins` entry point under the namespace `openai` (see DESIGNS.md No. 13).

```bash
uv add harnessweaver-openai        # or: uv add "harnessweaver[openai]"
```

## `openai.chat`: a model provider

Any OpenAI-compatible endpoint: LiteLLM Proxy, OpenAI, vLLM, Ollama.

```yaml
models:
  provider: openai.chat
  base_url: http://litellm:4000     # the gateway owns retries, fallbacks and keys (RULES R5, S1)
  api_key_env: LITELLM_API_KEY      # default OPENAI_API_KEY; keys never go in the spec
  default: fast
  aliases: { fast: gpt-x-mini, strong: gpt-x }
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `base_url` | the SDK's default | Endpoint, usually the gateway |
| `api_key_env` | `OPENAI_API_KEY` | Environment variable with the key |
| `timeout` | `60s` | Per request |
| `max_retries` | `0` | SDK retries; the gateway retries (R5) |
| `max_tokens_param` | `max_tokens` | Or `max_completion_tokens` |
| `cost_header` | `x-litellm-response-cost` | The gateway's reported cost, used before `models.prices` |
| `default_headers` | none | Extra headers on every request |
| `hold_stream` | `false` | Deliver a streamed answer's chunks only once it has finished, so nothing from a declined answer reaches the app. Output is no longer live |
| `block_empty_answers` | `false` | Treat an answer with no text and no tool calls as declined. LiteLLM drops a streamed refusal, leaving only that; but a model may also just have nothing to add |

A request the model declines ends the run `blocked` with code `model_refusal`, here and through `harness.instrument(client)`, and its tokens and cost still count. It is recognized by the message's `refusal` field, also under `provider_specific_fields` where LiteLLM moves it, or the finish reason `content_filter`, which is how LiteLLM reports a Claude refusal, so an answer a content filter cut short ends the same way. An endpoint that returns a refusal as ordinary text can't be told apart from an answer: use a `regex.deny` output guard on the wording you see.

A gateway can serve Claude through this provider, but only what Chat Completions carries gets through: thinking isn't requested or replayed, `effort` isn't a setting, and there are no server-side refusal fallbacks. Use `anthropic.messages` from `harnessweaver-anthropic` for those.

## `harness.instrument(client)`

```python
client = harness.instrument(AsyncOpenAI(base_url=LITELLM_URL))
answer = await client.chat.completions.create(model="gpt-x-mini", messages=[...])
```

`chat.completions.create` calls are governed: traced, costed, budgeted and guarded (`input.before` on the messages, `output.before` on the answer), with redactions written back. Everything else passes through. Streaming through an instrumented client is *planned* and raises for now.

## Conformance

From this package's directory (at the repository root, `make conformance` checks every first-party plugin):

```bash
uv run pytest --harnessweaver-conformance=openai
```
