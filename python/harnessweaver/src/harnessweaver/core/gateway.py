"""The neutral tool allow-list ``harnessweaver gateway mcp`` writes (ADR-0039).

Gateways that sit between apps and tools (an MCP gateway, LiteLLM's tool-permission
guardrail) can't see a run: what it has read, who approves, which tenant it is
for. So the allow-list names only the tools a gateway can let through on the
manifest alone, each with the digest to pin and the scopes to require, and lists
every other tool as withheld, with the reason. A gateway allows nothing else.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from harnessweaver.core.manifests import Transport

__all__ = ["AllowedTool", "GatewayMetadata", "ToolAllowList", "WithheldTool"]


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AllowedTool(_Strict):
    """A tool a gateway may let through."""

    tool: str
    transport: Transport
    server: str | None = Field(default=None, description="The MCP server, for mcp tools.")
    digest: str = Field(description="The definition digest to pin (S2, rug-pull defense).")
    scopes: tuple[str, ...] = ()


class WithheldTool(_Strict):
    """A tool only the harness may run, and why."""

    tool: str
    reason: str


class GatewayMetadata(_Strict):
    name: str = Field(description="The spec the list was generated from.")


class ToolAllowList(_Strict):
    """A ``kind: ToolAllowList`` document: deny by default, allow ``tools``."""

    api_version: Literal["harnessweaver/v1"] = Field(default="harnessweaver/v1", alias="apiVersion")
    kind: Literal["ToolAllowList"] = "ToolAllowList"
    metadata: GatewayMetadata
    default: Literal["deny"] = "deny"
    tools: tuple[AllowedTool, ...] = ()
    withheld: tuple[WithheldTool, ...] = ()

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)
