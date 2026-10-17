# harnessweaver-monty

A first-party [HarnessWeaver](../../../README.md) plugin for Monty sandbox. It contributes a `monty.sandbox` executor that runs code-executing tools in the pydantic-monty sandbox.

It is built on the same plugin contract any third-party plugin uses: one `hw.Plugin` object, published through the `harnessweaver.plugins` entry point under the namespace `monty` (see DESIGNS.md §13).

```bash
uv add harnessweaver-monty        # or: uv add "harnessweaver[monty]"
```

> Status: package skeleton. The plugin's contributions are not implemented yet.
