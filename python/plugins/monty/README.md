# harnessweaver-monty

A first-party [HarnessWeaver](../../../README.md) plugin for the Monty sandbox. It contributes `monty.sandbox`, a `Sandbox` that runs code-executing tools in [pydantic-monty](https://github.com/pydantic/monty) worker processes, never in the host process (RULES S4).

It is built on the same plugin contract any third-party plugin uses: one `hw.Plugin` object, published through the `harnessweaver.plugins` entry point under the namespace `monty` (see DESIGNS.md No. 13).

```bash
uv add harnessweaver-monty        # or: uv add "harnessweaver[monty]"
```

```yaml
# tools/python.tool.yaml
apiVersion: harnessweaver/v1
kind: Tool
metadata: { name: python }
spec:
  transport: code
  sandbox: monty                # short for monty.sandbox
  description: Run Python over the given rows and return the last expression.
  input_schema:
    type: object
    properties: { code: { type: string }, rows: { type: array } }
    required: [code]
  limits: { timeout: 2s, max_memory_mb: 64 }
```

The code in the `code` argument runs with the other arguments as globals, and the tool returns `{value, stdout}`, or `{error, stdout}` when the code raises. Sandboxed code can't open host files, reach the network or read the environment, and the manifest's `limits` cap its time, memory and printed output. Each call gets a fresh worker, so nothing leaks between calls. Importing the plugin imports nothing from pydantic-monty (S8).
