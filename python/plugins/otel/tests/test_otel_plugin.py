"""The otel plugin: SDK setup only when asked, never over an app's own setup (R5)."""

import io
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from loguru import logger
from opentelemetry import trace
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

import harnessweaver as hw
from harnessweaver.core.registry import PluginCatalog, PluginSource
from harnessweaver_otel import OtelSdk, OtelSdkConfig

CATALOG = PluginCatalog([PluginSource("otel", "harnessweaver_otel:plugin", "entry_point")])


class Captured:
    def __init__(self) -> None:
        self.providers: list[tuple[Any, Any]] = []

    def __call__(self, tracer_provider: Any, meter_provider: Any) -> None:
        self.providers.append((tracer_provider, meter_provider))


def configured(exporter: str, endpoint: str | None = None) -> tuple[OtelSdk, Captured]:
    captured = Captured()
    sdk = OtelSdk(OtelSdkConfig(export_interval=timedelta(seconds=5)), install=captured)
    sdk.configure(service_name="svc", exporter=exporter, endpoint=endpoint)
    return sdk, captured


def test_console_and_none_exporters() -> None:
    sdk, captured = configured("console")
    tracer_provider, meter_provider = captured.providers[0]
    assert isinstance(tracer_provider, TracerProvider)
    assert tracer_provider.resource.attributes["service.name"] == "svc"
    assert sdk.meter_provider is meter_provider
    _, quiet = configured("none")
    assert len(quiet.providers) == 1


def test_otlp_is_not_installed_in_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    lines: list[str] = []
    sink = logger.add(lines.append, format="{name} | {message}")
    try:
        configured("otlp", "http://collector:4318")
        assert lines == []  # the plugin is silent until the app opts in (ADR-0024)
        logger.enable("harnessweaver_otel")
        sdk, _ = configured("otlp", "http://collector:4318")
    finally:
        logger.remove(sink)
        logger.disable("harnessweaver_otel")
    assert [line.strip() for line in lines] == [
        "harnessweaver_otel.sdk | test mode: the OTLP exporter isn't installed (R14)"
    ]
    assert sdk.tracer_provider is not None
    # Outside test mode the OTLP exporters are built; stand-ins keep this test offline (R14).
    endpoints: list[str | None] = []

    class SpanStandIn(SpanExporter):
        def __init__(self, endpoint: str | None = None) -> None:
            endpoints.append(endpoint)

        def export(self, spans: Any) -> SpanExportResult:
            return SpanExportResult.SUCCESS

    class MetricStandIn(ConsoleMetricExporter):
        def __init__(self, endpoint: str | None = None) -> None:
            endpoints.append(endpoint)
            super().__init__(out=io.StringIO())

    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter", SpanStandIn
    )
    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter", MetricStandIn
    )
    monkeypatch.delenv(hw.ports.TEST_MODE_ENV)  # type: ignore[attr-defined]
    live, captured = configured("otlp", "http://collector:4318/")
    assert captured.providers
    assert endpoints == ["http://collector:4318/v1/traces", "http://collector:4318/v1/metrics"]
    live.tracer_provider.shutdown()
    live.meter_provider.shutdown()


def test_an_existing_sdk_setup_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    installs: list[Any] = []
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: TracerProvider())
    monkeypatch.setattr("harnessweaver_otel.sdk._install_globals", lambda *a: installs.append(a))
    sdk = OtelSdk(OtelSdkConfig())
    sdk.configure(service_name="svc", exporter="console", endpoint=None)
    assert sdk.tracer_provider is None
    assert installs == []


def test_the_harness_uses_it_when_configure_sdk_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(OtelSdk, "configure", lambda self, **kwargs: calls.append(kwargs))
    document = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Harness",
        "metadata": {"name": "traced-app"},
        "observability": {
            "configure_sdk": True,
            "exporter": "otlp",
            "endpoint": "http://c:4318",
            "export_interval": "10s",
        },
    }
    path = tmp_path / "harness.yaml"
    path.write_text(json.dumps(document), encoding="ascii")
    hw.Harness.load(path, catalog=CATALOG)
    assert calls == [
        {"service_name": "traced-app", "exporter": "otlp", "endpoint": "http://c:4318"}
    ]
