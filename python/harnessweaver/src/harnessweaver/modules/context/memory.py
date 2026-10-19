"""The built-in ``Memory`` provider: namespaced key-value entries with expiry (ADR-0031).

It is a store, not a memory model (R12): it keeps what the app puts and hands it
back. The harness picks the namespace, ``(tenant, principal, task)``.
"""

from datetime import datetime

from pydantic import JsonValue

from harnessweaver.core.plugins import provider

__all__ = ["MemoryStore"]

type _Entry = tuple[JsonValue, datetime | None]


@provider(port="Memory", name="memory", deterministic=True, latency_class="fast")
class MemoryStore:
    """In-process entries; they don't outlive the process."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, ...], dict[str, _Entry]] = {}

    async def put(
        self, namespace: tuple[str, ...], key: str, value: JsonValue, *, expires_at: datetime | None
    ) -> None:
        self._entries.setdefault(namespace, {})[key] = (value, expires_at)

    def _live(self, namespace: tuple[str, ...], now: datetime) -> dict[str, _Entry]:
        entries = self._entries.get(namespace, {})
        for key in [
            k for k, (_, expires) in entries.items() if expires is not None and expires <= now
        ]:
            del entries[key]
        return entries

    async def get(self, namespace: tuple[str, ...], key: str, *, now: datetime) -> JsonValue | None:
        entry = self._live(namespace, now).get(key)
        return entry[0] if entry is not None else None

    async def delete(self, namespace: tuple[str, ...], key: str) -> None:
        self._entries.get(namespace, {}).pop(key, None)

    async def entries(self, namespace: tuple[str, ...], *, now: datetime) -> dict[str, JsonValue]:
        return {key: value for key, (value, _) in self._live(namespace, now).items()}
