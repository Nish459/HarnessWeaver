"""HarnessWeaver plugin for the OpenTelemetry SDK.

Contributes ``otel.sdk``, which configures the OpenTelemetry SDK and an exporter
when ``observability.configure_sdk: true`` (R5, ADR-0010). Importing this module
imports nothing from the SDK (RULES S8).
"""

from importlib.metadata import version as _version

import harnessweaver as hw
from harnessweaver_otel.sdk import OtelSdk, OtelSdkConfig

__version__: str = _version("harnessweaver-otel")

plugin = hw.Plugin(
    namespace="otel",
    version=__version__,
    providers=[OtelSdk],
    description="OpenTelemetry SDK and exporter setup for the harness's spans and metrics.",
)

__all__ = ["OtelSdk", "OtelSdkConfig", "__version__", "plugin"]
