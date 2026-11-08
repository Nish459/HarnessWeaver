# harnessweaver-otel

A first-party [HarnessWeaver](https://github.com/Wise-DreamerZ/HarnessWeaver) plugin that sets up the OpenTelemetry SDK. It is built on the same plugin contract any third-party plugin uses (see DESIGNS.md No. 13).

```bash
uv add harnessweaver-otel          # or: uv add "harnessweaver[otel]"
```

The core only uses the OpenTelemetry API, so its spans and metrics go wherever the app's own SDK setup sends them. If the app has none, ask the harness to set it up:

```yaml
observability:
  configure_sdk: true
  exporter: otlp                     # none | console | otlp
  endpoint: http://otel-collector:4318
  service_name: invoice-extractor    # default: metadata.name
  export_interval: 30s               # metrics, default 60s
```

`otel.sdk` installs SDK tracer and meter providers with the chosen exporter, once, when the harness loads. If the app already installed SDK providers it changes nothing (one owner, RULES R5). The OTLP exporters also read the standard `OTEL_EXPORTER_OTLP_*` environment variables. With `HARNESSWEAVER_TEST_MODE=1` the OTLP exporter isn't installed (R14).

## Conformance

From this package's directory (at the repository root, `make conformance` checks every first-party plugin):

```bash
uv run pytest --harnessweaver-conformance=otel
```
