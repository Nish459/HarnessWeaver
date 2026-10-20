"""Guards declared ``where: sidecar``: the provider runs in harnessd (DESIGNS No. 24).

The guard keeps its place on the hook bus, its action, mode, fail mode and
timeout; only the provider's ``check`` is answered by the sidecar, through
``POST /v1/guards/providers/{name}:check`` (ADR-0038). That lets an app use a
provider that is installed only next to the sidecar, such as a heavy PII model.
A sidecar that can't be reached raises ``ProviderError``, which the guard's
``fail_mode`` turns into a block or a pass (R2).
"""

import os
import urllib.parse
from collections.abc import Mapping

from pydantic import JsonValue, ValidationError

from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import ErrorInfo, ProviderError
from harnessweaver.core.guards import GuardResult
from harnessweaver.core.sidecar import ProviderCheck
from harnessweaver.modules.tools.transports import send_http
from harnessweaver.spec.models import SidecarSpec

__all__ = ["RemoteGuardrail"]

TIMEOUT_SECONDS = 10.0
"""How long one remote check may take, unless the guard sets its own ``timeout``."""


class RemoteGuardrail:
    """A ``Guardrail`` whose ``check`` runs in the sidecar the spec's ``sidecar`` names.

    The bearer token is read from ``sidecar.token_env`` on every call, so a
    rotated token is picked up without a reload.
    """

    def __init__(
        self,
        sidecar: SidecarSpec,
        name: str,
        settings: Mapping[str, JsonValue],
        stage: str,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        assert sidecar.url is not None  # the guardrails module checks it at load
        self.url = f"{sidecar.url.rstrip('/')}/v1/guards/providers/{urllib.parse.quote(name)}:check"
        self.token_env = sidecar.token_env
        self.name = name
        self.settings = dict(settings)
        self.stage = stage
        self.timeout = timeout

    async def check(self, content: str, env: Envelope) -> GuardResult:
        """Ask the sidecar to run the provider on ``content``.

        Raises:
            ProviderError: Without a token, in test mode, or when the sidecar fails,
                refuses or answers something that isn't a ``GuardResult``.
        """
        token = os.environ.get(self.token_env)
        if not token:
            raise ProviderError(f"guard {self.name}: set {self.token_env} to call the sidecar")
        request = ProviderCheck(
            content=content, envelope=env, settings=self.settings, stage=self.stage
        )
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        status, reply = await send_http(
            self.url, request.model_dump_json().encode("utf-8"), headers, self.timeout
        )
        if status != 200:
            raise ProviderError(
                f"guard {self.name}: the sidecar answered HTTP {status}{_why(reply)}",
                status=status,
            )
        try:
            return GuardResult.model_validate_json(reply)
        except ValidationError:
            raise ProviderError(
                f"guard {self.name}: the sidecar's answer isn't a GuardResult"
            ) from None


def _why(reply: bytes) -> str:
    # The sidecar's ErrorInfo names the error; its message never holds content (R9).
    try:
        info = ErrorInfo.model_validate_json(reply)
    except ValidationError:
        return ""
    return f" ({info.type}: {info.message})"
