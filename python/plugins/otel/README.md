# harnessweaver-otel

A first-party [HarnessWeaver](../../../README.md) plugin for OpenTelemetry SDK. It contributes `otel.sdk`, which configures the OpenTelemetry SDK and OTLP exporter when `observability.configure_sdk: true`.

It is built on the same plugin contract any third-party plugin uses: one `hw.Plugin` object, published through the `harnessweaver.plugins` entry point under the namespace `otel` (see DESIGNS.md §13).

```bash
uv add harnessweaver-otel        # or: uv add "harnessweaver[otel]"
```

> Status: package skeleton. The plugin's contributions are not implemented yet.
