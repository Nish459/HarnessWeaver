# harnessweaver-cel

A first-party [HarnessWeaver](../../../README.md) plugin for CEL policies. It contributes a `cel.policy` policy engine that evaluates full CEL through cel-python.

It is built on the same plugin contract any third-party plugin uses: one `hw.Plugin` object, published through the `harnessweaver.plugins` entry point under the namespace `cel` (see DESIGNS.md No. 13).

```bash
uv add harnessweaver-cel        # or: uv add "harnessweaver[cel]"
```

> Status: package skeleton. The plugin's contributions are not implemented yet.
