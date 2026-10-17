# harnessweaver-openai

A first-party [HarnessWeaver](../../../README.md) plugin for OpenAI-compatible models. It contributes an `openai.chat` model provider for any OpenAI-compatible endpoint (LiteLLM Proxy, OpenAI, vLLM, Ollama) and an adapter for `harness.instrument(OpenAI client)`.

It is built on the same plugin contract any third-party plugin uses: one `hw.Plugin` object, published through the `harnessweaver.plugins` entry point under the namespace `openai` (see DESIGNS.md No. 13).

```bash
uv add harnessweaver-openai        # or: uv add "harnessweaver[openai]"
```

> Status: package skeleton. The plugin's contributions are not implemented yet.
