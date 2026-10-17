"""HarnessWeaver plugin for OpenTelemetry SDK.

Contributes otel.sdk, which configures the OpenTelemetry SDK and OTLP exporter
when observability.configure_sdk: true.
"""

from importlib.metadata import version as _version

__version__: str = _version("harnessweaver-otel")

__all__ = ["__version__"]
