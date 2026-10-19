"""Governor step 9: what a tool's result goes through before anything else sees it.

In order: the manifest's sanitizers (``pii_redact``, then ``strip_instructions``),
truncation to ``max_bytes`` of UTF-8, and the ``untrusted`` label (S3). Truncated
output becomes a string: a JSON result is cut as its compact JSON text (no spaces).
"""

import json
import re
from collections.abc import Awaitable, Callable

from pydantic import JsonValue

from harnessweaver.core.envelope import Envelope
from harnessweaver.core.manifests import OutputPolicy
from harnessweaver.core.tools import ToolResult
from harnessweaver.modules.guardrails import INJECTION_PATTERNS, PiiRegex

__all__ = ["REMOVED", "sanitize"]

REMOVED = "[removed]"
"""What ``strip_instructions`` puts in place of an instruction-like phrase."""

_INSTRUCTIONS = [
    re.compile(pattern, re.ASCII | re.IGNORECASE) for _, pattern, _ in INJECTION_PATTERNS
]
_PII = PiiRegex()


async def _strings(value: JsonValue, change: Callable[[str], Awaitable[str]]) -> JsonValue:
    if isinstance(value, str):
        return await change(value)
    if isinstance(value, list):
        return [await _strings(item, change) for item in value]
    if isinstance(value, dict):
        return {key: await _strings(item, change) for key, item in value.items()}
    return value


def _cut(text: str, max_bytes: int) -> str:
    return text.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")


async def sanitize(
    result: ToolResult, policy: OutputPolicy, max_bytes: int, env: Envelope
) -> tuple[ToolResult, list[str]]:
    """Apply ``policy`` to ``result``. Returns the new result and what was done, for the trace."""
    output = result.output
    done: list[str] = []

    async def redact(text: str) -> str:
        checked = await _PII.check(text, env)
        return checked.content if checked.content is not None else text

    async def strip(text: str) -> str:
        for pattern in _INSTRUCTIONS:
            text = pattern.sub(REMOVED, text)
        return text

    for name, change in (("pii_redact", redact), ("strip_instructions", strip)):
        if name in policy.sanitize:
            changed = await _strings(output, change)
            if changed != output:
                done.append(name)
            output = changed
    truncated = result.truncated
    text = (
        output
        if isinstance(output, str)
        else json.dumps(output, ensure_ascii=False, separators=(",", ":"))
    )
    if len(text.encode("utf-8")) > max_bytes:
        output, truncated = _cut(text, max_bytes), True
        done.append(f"truncated to {max_bytes} bytes")
    untrusted = policy.label == "untrusted"
    updated = result.model_copy(
        update={"output": output, "truncated": truncated, "untrusted": untrusted}
    )
    return updated, done
