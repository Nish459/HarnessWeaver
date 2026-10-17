# harnessweaver-anthropic

A first-party [HarnessWeaver](../../../README.md) plugin for Anthropic models. It contributes an `anthropic.messages` model provider for the Claude Messages API and an adapter for `harness.instrument(Anthropic client)`.

It is built on the same plugin contract any third-party plugin uses: one `hw.Plugin` object, published through the `harnessweaver.plugins` entry point under the namespace `anthropic` (see DESIGNS.md No. 13).

```bash
uv add harnessweaver-anthropic        # or: uv add "harnessweaver[anthropic]"
```

> Status: package skeleton. The plugin's contributions are not implemented yet.
