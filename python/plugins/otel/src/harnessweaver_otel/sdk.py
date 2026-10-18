"""The ``otel.sdk`` provider: OpenTelemetry SDK and exporter setup (ADR-0010, R5).

Used only when the spec asks for it:

```yaml
observability:
  configure_sdk: true
  exporter: otlp                     # none | console | otlp
  endpoint: http://otel-collector:4318
  service_name: invoice-extractor    # default: metadata.name
  export_interval: 30s               # metrics
```

The core only uses the OpenTelemetry *API*. This provider installs SDK tracer
and meter providers with the chosen exporter as the process-wide providers, so
the harness's spans and metrics go there. If the app already installed SDK
providers it changes nothing (one owner, R5). The OTLP exporters also read the
standard ``OTEL_EXPORTER_OTLP_*`` variables (headers, certificates). With
``HARNESSWEAVER_TEST_MODE=1`` the OTLP exporter isn't installed (R14).
"""

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import harnessweaver as hw
from harnessweaver.ports import network_allowed

__all__ = ["OtelSdk", "OtelSdkConfig"]

_log = logging.getLogger("harnessweaver.otel")

type Installer = Callable[[Any, Any], None]
"""Makes ``(tracer_provider, meter_provider)`` the process-wide providers."""


class OtelSdkConfig(BaseModel):
    """Extra ``observability`` settings for ``otel.sdk``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    export_interval: hw.Duration = Field(default=timedelta(seconds=60), description="Metrics.")


def _install_globals(tracer_provider: Any, meter_provider: Any) -> None:
    from opentelemetry import metrics, trace

    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)


def _sdk_already_configured() -> bool:
    from opentelemetry import trace

    return not isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider)


@hw.provider(
    port="Telemetry",
    name="otel.sdk",
    config=OtelSdkConfig,
    deterministic=True,
    latency_class="fast",
)
class OtelSdk:
    """Sets up the OpenTelemetry SDK once, when the harness loads."""

    def __init__(self, config: OtelSdkConfig, install: Installer | None = None) -> None:
        self.config = config
        self._install = install or _install_globals
        self.tracer_provider: Any = None
        self.meter_provider: Any = None

    def configure(self, *, service_name: str, exporter: str, endpoint: str | None) -> None:
        """Install SDK providers with ``exporter``; leave an app's own setup alone (R5)."""
        if self._install is _install_globals and _sdk_already_configured():
            _log.info("OpenTelemetry SDK is already configured; otel.sdk leaves it as it is")
            return
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            MetricReader,
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )

        resource = Resource.create({"service.name": service_name})
        tracer_provider = TracerProvider(resource=resource)
        readers: list[MetricReader] = []
        interval = self.config.export_interval.total_seconds() * 1000
        if exporter == "console":
            tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            readers.append(
                PeriodicExportingMetricReader(
                    ConsoleMetricExporter(), export_interval_millis=interval
                )
            )
        elif exporter == "otlp":
            if not network_allowed():
                _log.warning("test mode: the OTLP exporter isn't installed (R14)")
            else:
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                    OTLPMetricExporter,
                )
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                base = endpoint.rstrip("/") if endpoint else None
                spans = OTLPSpanExporter(endpoint=f"{base}/v1/traces" if base else None)
                tracer_provider.add_span_processor(BatchSpanProcessor(spans))
                metrics = OTLPMetricExporter(endpoint=f"{base}/v1/metrics" if base else None)
                readers.append(
                    PeriodicExportingMetricReader(metrics, export_interval_millis=interval)
                )
        meter_provider = MeterProvider(resource=resource, metric_readers=readers)
        self.tracer_provider, self.meter_provider = tracer_provider, meter_provider
        self._install(tracer_provider, meter_provider)
