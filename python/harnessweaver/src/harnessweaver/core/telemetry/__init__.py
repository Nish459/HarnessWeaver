"""Telemetry through the OpenTelemetry API only (DESIGNS No. 22, ADR-0010).

The core never configures an SDK or exporter: without one, every call here is a
cheap no-op. The ``otel.sdk`` provider (plugin ``harnessweaver-otel``) sets the
SDK up when ``observability.configure_sdk`` is true (R5).

Spans follow the OpenTelemetry GenAI conventions (``chat {model}``,
``execute_tool {tool}``) plus the framework's own ``harness.*`` spans. The
conventions are still in Development, so the attribute names are pinned here
as of :data:`SEMCONV_VERSION`; a test compares them with the installed
``opentelemetry-semantic-conventions`` package.

Content (prompts, outputs, tool arguments and results) is recorded only when
``capture_content`` is on, and only after redaction (R9).
"""

from harnessweaver.core.telemetry.names import (
    ERROR_TYPE,
    SCHEMA_URL,
    SEMCONV_VERSION,
    GenAI,
    HarnessAttr,
)
from harnessweaver.core.telemetry.recorder import Telemetry, elapsed

__all__ = [
    "ERROR_TYPE",
    "SCHEMA_URL",
    "SEMCONV_VERSION",
    "GenAI",
    "HarnessAttr",
    "Telemetry",
    "elapsed",
]
