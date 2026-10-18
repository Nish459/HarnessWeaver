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

## `harness.instrument(client)`

```python
client = harness.instrument(AsyncOpenAI(base_url=LITELLM_URL))
answer = await client.chat.completions.create(model="gpt-x-mini", messages=[...])
```

`chat.completions.create` calls are governed: traced, costed, budgeted and guarded (`input.before` on the messages, `output.before` on the answer), with redactions written back. Everything else passes through. Streaming through an instrumented client is *planned* and raises for now.
