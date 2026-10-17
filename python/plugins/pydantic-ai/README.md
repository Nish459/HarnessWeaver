# harnessweaver-pydantic-ai

A first-party [HarnessWeaver](../../../README.md) plugin for Pydantic AI. It contributes a `pydantic_ai.agent` runner and an adapter that governs an existing Pydantic AI agent through `harness.wrap(agent)`.

It is built on the same plugin contract any third-party plugin uses: one `hw.Plugin` object, published through the `harnessweaver.plugins` entry point under the namespace `pydantic_ai` (see DESIGNS.md No. 13).

```bash
uv add harnessweaver-pydantic-ai        # or: uv add "harnessweaver[pydantic-ai]"
```

> Status: package skeleton. The plugin's contributions are not implemented yet.
