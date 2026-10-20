"""Tool manifests: the ``kind: Tool`` documents no tool runs without (S2, DESIGNS No. 17).

```yaml
apiVersion: harnessweaver/v1
kind: Tool
metadata: { name: refund_payment, version: 2.1.0, owner: payments-team }
spec:
  transport: native                      # native | http | code | mcp
  handler: "app.tools:refund_payment"
  description: Refund part or all of a payment.
  input_schema: { $ref: schemas/refund_args.json }
  definition_digest: "sha256:..."        # pins {name, description, input_schema}
  side_effect: write_external
  risk: high
  data_access: ["pii:customer"]
  egress: [payments.internal]
  rate_limit: { per_principal: 10/m, per_tenant: 200/h }
  approval: { when: "args.amount_usd > 100", approver_role: finance }
  output: { max_bytes: 20000, sanitize: [strip_instructions, pii_redact], label: untrusted }
```

``transport: code`` runs the code in one argument (``code_arg``) in the named
``sandbox``, never in the host process (S4, ADR-0027).
"""

import re
from datetime import timedelta
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from harnessweaver.core.digests import canonical_digest
from harnessweaver.core.durations import Duration
from harnessweaver.core.messages import ToolSpec
from harnessweaver.core.tools import Risk, SandboxLimits, SideEffect, ToolInfo

__all__ = [
    "DIGEST_PATTERN",
    "ManifestApproval",
    "OutputPolicy",
    "RateLimit",
    "ToolManifest",
    "ToolManifestSpec",
    "ToolMetadata",
    "Transport",
    "definition_digest",
    "parse_rate",
]

DIGEST_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"

_RATE = re.compile(r"^\s*([1-9][0-9]*)\s*/\s*(s|m|h|d)\s*$")
_UNITS: Final = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def parse_rate(text: str) -> tuple[int, float]:
    """``"10/m"`` -> ``(10, 60.0)``: calls allowed per window, and the window in seconds.

    Raises:
        ValueError: For anything but ``<count>/<s|m|h|d>``.
    """
    found = _RATE.match(text)
    if found is None:
        raise ValueError(f"rate {text!r} must look like 10/m (per s, m, h or d)")
    return int(found.group(1)), _UNITS[found.group(2)]


def definition_digest(name: str, description: str, input_schema: dict[str, JsonValue]) -> str:
    """The digest that pins what a model is told about a tool (S2, rug-pull defense)."""
    return canonical_digest(
        {"name": name, "description": description, "input_schema": input_schema}
    )


class Transport(StrEnum):
    """How a tool is reached."""

    NATIVE = "native"
    HTTP = "http"
    CODE = "code"
    MCP = "mcp"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RateLimit(_Strict):
    """Calls allowed per principal and per tenant, such as ``10/m`` or ``200/h``."""

    per_principal: str | None = None
    per_tenant: str | None = None

    @field_validator("per_principal", "per_tenant")
    @classmethod
    def _parses(cls, value: str | None) -> str | None:
        if value is not None:
            parse_rate(value)
        return value


class ManifestApproval(_Strict):
    """When a call needs a human: ``when`` is a cel-lite predicate over the policy names."""

    when: str | None = None
    approver_role: str | None = None


class OutputPolicy(_Strict):
    """What the governor does to a result before anything else sees it (step 9)."""

    max_bytes: int | None = Field(
        default=None, gt=0, description="Defaults to tools.max_output_bytes."
    )
    sanitize: tuple[Literal["strip_instructions", "pii_redact"], ...] = ()
    label: Literal["untrusted", "trusted"] = "untrusted"


class ToolMetadata(_Strict):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    version: str | None = None
    owner: str | None = None


class ToolManifestSpec(_Strict):
    """A tool's definition, transport and governance."""

    transport: Transport = Transport.NATIVE
    description: str = Field(default="", description="What the model is told the tool does.")
    input_schema: dict[str, JsonValue] = Field(
        default_factory=lambda: dict[str, JsonValue]({"type": "object"})
    )
    definition_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    handler: str | None = Field(
        default=None,
        description="native: 'module:function'. Required in a manifest file; a tool given in "
        "code is run by its own backend.",
    )
    url: str | None = Field(default=None, description="http: where the arguments are POSTed.")
    server: str | None = Field(
        default=None, description="mcp: the MCP server that serves the tool, e.g. mcp://payments."
    )
    headers_env: dict[str, str] = Field(
        default_factory=dict[str, str],
        description="http: header name -> environment variable holding its value (S1).",
    )
    sandbox: str = Field(default="none", description="code: the Sandbox provider, e.g. monty.")
    code_arg: str = Field(default="code", description="code: the argument holding the code.")
    limits: SandboxLimits = SandboxLimits()
    timeout: Duration = timedelta(seconds=30)
    side_effect: SideEffect = SideEffect.NONE
    risk: Risk = Risk.LOW
    data_access: tuple[str, ...] = ()
    egress: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    tenants: tuple[str, ...] = Field(
        default=(), description="Tenants it is enabled for; empty is all."
    )
    enabled: bool = True
    rate_limit: RateLimit | None = None
    approval: ManifestApproval | None = None
    output: OutputPolicy = OutputPolicy()

    @model_validator(mode="after")
    def _transport_fields(self) -> Self:
        if self.transport is Transport.HTTP and not self.url:
            raise ValueError("an http tool needs a url")
        if (self.transport is Transport.MCP) != (self.server is not None):
            raise ValueError("an mcp tool names its server, and only an mcp tool does")
        if self.transport is Transport.CODE and self.sandbox == "none":
            raise ValueError("a code tool must name a sandbox, such as monty (S4)")
        if self.transport is not Transport.CODE and self.sandbox != "none":
            raise ValueError("only code tools (transport: code) run in a sandbox")
        return self


class ToolManifest(_Strict):
    """A ``kind: Tool`` document."""

    api_version: Literal["harnessweaver/v1"] = Field(default="harnessweaver/v1", alias="apiVersion")
    kind: Literal["Tool"] = "Tool"
    metadata: ToolMetadata
    spec: ToolManifestSpec

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    @property
    def name(self) -> str:
        return self.metadata.name

    def info(self) -> ToolInfo:
        """The facts policies and middleware decide on."""
        spec = self.spec
        return ToolInfo(
            name=self.name,
            version=self.metadata.version,
            side_effect=spec.side_effect,
            risk=spec.risk,
            egress=spec.egress,
            data_access=spec.data_access,
            scopes=spec.scopes,
        )

    def tool_spec(self) -> ToolSpec:
        """The tool as offered to a model."""
        return ToolSpec(
            name=self.name, description=self.spec.description, input_schema=self.spec.input_schema
        )

    def computed_digest(self) -> str:
        """The digest of the definition as written; compare with ``definition_digest``."""
        return definition_digest(self.name, self.spec.description, self.spec.input_schema)
