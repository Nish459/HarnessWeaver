# harnessweaver

The core of [HarnessWeaver](../../README.md), *the composable AI harness framework*: the spec loader, the 13-point hook bus, envelope and budgets, the error taxonomy, the runners, the built-in modules and the test kit.

```bash
uv add harnessweaver                 # core only: pydantic, opentelemetry-api, pyyaml, anyio
uv add "harnessweaver[openai]"       # plus a first-party plugin
uv add "harnessweaver[all]"          # every first-party plugin, the CLI and the sidecar
```

> Status: package skeleton. See the repository README for what the framework does.
