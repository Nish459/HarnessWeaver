"""The tool registry: tools from manifests, executed through their transport (S2)."""

from collections.abc import Callable, Sequence
from typing import Any

import anyio

from harnessweaver._imports import import_object
from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import SpecError
from harnessweaver.core.manifests import ToolManifest, Transport
from harnessweaver.core.messages import ToolCall
from harnessweaver.core.ports import Sandbox, ToolBackend, ToolDescription
from harnessweaver.core.state import call_digest
from harnessweaver.core.tools import ToolResult
from harnessweaver.modules.tools.transports import (
    HttpSender,
    NativeHandler,
    call_code,
    call_http,
    call_native,
    send_http,
)

__all__ = ["ChainedTools", "ManifestTools"]


class ManifestTools:
    """A ``ToolBackend`` built from manifests.

    Native handlers are imported and sandboxes built when the harness loads, so a
    wrong path fails then (R4). A manifest whose ``definition_digest`` doesn't
    match its definition is still listed, and the governor blocks its calls (S2).

    Args:
        manifests: The loaded manifests.
        sandbox: Builds the ``Sandbox`` provider a code tool names.
        http: Sends http tools' requests; tests pass a fake (R14).

    Raises:
        SpecError: For a handler that can't be imported, or ``transport: mcp``.
    """

    def __init__(
        self,
        manifests: Sequence[ToolManifest],
        *,
        sandbox: Callable[[str], Sandbox] | None = None,
        http: HttpSender | None = None,
    ) -> None:
        self._http = http or send_http
        self._tools: dict[str, tuple[ToolManifest, ToolDescription]] = {}
        self._handlers: dict[str, NativeHandler] = {}
        self._sandboxes: dict[str, Sandbox] = {}
        for manifest in manifests:
            spec, where = manifest.spec, f"tool {manifest.name}"
            if spec.transport is Transport.MCP:
                raise SpecError(f"{where}: transport mcp isn't supported yet (planned)")
            if spec.transport is Transport.NATIVE:
                if not spec.handler:
                    raise SpecError(f"{where}: a native tool needs a handler ('module:function')")
                function: Any = import_object(spec.handler, f"{where}: spec.handler")
                if not callable(function):
                    raise SpecError(f"{where}: spec.handler {spec.handler!r} isn't callable")
                self._handlers[manifest.name] = NativeHandler(function)
            if spec.transport is Transport.CODE:
                if sandbox is None:
                    raise SpecError(f"{where}: code tools need a sandbox provider")
                self._sandboxes[manifest.name] = sandbox(spec.sandbox)
            self._tools[manifest.name] = (manifest, ToolDescription.from_manifest(manifest))

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self, name: str) -> ToolDescription | None:
        found = self._tools.get(name)
        return found[1] if found is not None else None

    async def execute(self, call: ToolCall, env: Envelope) -> ToolResult:
        """Run the call through its transport, within the manifest's ``timeout``."""
        manifest, _ = self._tools[call.name]
        key = f"{env.run_id}:{call_digest(call)}"
        args = call.arguments
        with anyio.fail_after(manifest.spec.timeout.total_seconds()):
            match manifest.spec.transport:
                case Transport.NATIVE:
                    output = await call_native(self._handlers[call.name], args, key)
                case Transport.HTTP:
                    output = await call_http(manifest, args, key, self._http)
                case _:
                    ran = await call_code(manifest, args, self._sandboxes[call.name])
                    if ran.error is not None:
                        return ToolResult(
                            call_id=call.id,
                            output={"error": ran.error, "stdout": ran.stdout},
                            is_error=True,
                        )
                    output = {"value": ran.value, "stdout": ran.stdout}
        return ToolResult(call_id=call.id, output=output)


class ChainedTools:
    """Several backends as one: the first that knows a tool's name serves it."""

    def __init__(self, backends: Sequence[ToolBackend]) -> None:
        self.backends = list(backends)

    def describe(self, name: str) -> ToolDescription | None:
        for backend in self.backends:
            found = backend.describe(name)
            if found is not None:
                return found
        return None

    async def execute(self, call: ToolCall, env: Envelope) -> ToolResult:
        for backend in self.backends:
            if backend.describe(call.name) is not None:
                return await backend.execute(call, env)
        raise SpecError(f"no tool backend has {call.name!r}")
