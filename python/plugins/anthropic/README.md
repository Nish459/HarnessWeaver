# harnessweaver-anthropic

A first-party [HarnessWeaver](../../../README.md) plugin for Claude models. It is built on the same plugin contract any third-party plugin uses: one `hw.Plugin` object, published through the `harnessweaver.plugins` entry point under the namespace `anthropic` (see DESIGNS.md No. 13).

```bash
uv add harnessweaver-anthropic     # or: uv add "harnessweaver[anthropic]"
```

## `anthropic.messages`: a model provider

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
| `fallbacks` | `default` | Server-side refusal fallbacks (beta `server-side-fallback-2026-07-01`); `none` turns them off |
| `structured_outputs` | `false` | Send output schemas as `output_config.format` (they must meet its rules); otherwise the schema goes in the system prompt |
| `sampling` | `false` | Forward `temperature`; current models reject sampling parameters |
| `base_url`, `api_key_env`, `timeout`, `max_retries` | SDK defaults | Client settings. Credentials follow the SDK's own resolution unless `api_key_env` names a variable |

Server-side fallbacks are on by default: a request a model declines for policy reasons is re-run on Anthropic's recommended fallback model, and on a model without fallbacks the request simply runs alone. A request that is still declined ends the run `blocked` with code `model_refusal`.

Each answer's own content blocks, thinking included, are replayed unchanged on the next request of a tool loop, so the model's reasoning carries over (ADR-0022). An answer the harness changed (a redaction) is replayed without its thinking, consistently, so the history stays append-only.

## `harness.instrument(client)`

```python
client = harness.instrument(AsyncAnthropic())
message = await client.messages.create(model="claude-opus-5-5", max_tokens=1024, messages=[...])
```

`messages.create` calls are governed: traced, budgeted and guarded (`input.before` on the system prompt and message text, `output.before` on the answer), with redactions written back. Everything else, including `client.beta.messages`, passes through. Streaming through an instrumented client is *planned* and raises for now.

## Conformance

```bash
uv run pytest --harnessweaver-conformance=anthropic
```
