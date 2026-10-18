"""Cassettes: record a real model's answers once, replay them offline forever (RULES T2).

```python
cassette = Cassette("tests/cassettes/extract.json", provider=real_provider)  # records if missing
harness = harness_for_test("harness.yaml", model=cassette)
```

Requests are matched by a digest of what is sent (model, messages, tools, output
schema, sampling), in order: the same request asked twice replays the next
recorded answer for it. Replaying never calls the provider, so tests stay offline.

A cassette holds whatever the model answered: scrub personal data and secrets
before committing one (S7). ``scrub`` is applied to every recorded answer.
"""

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Final, Literal

import anyio.to_thread
from pydantic import JsonValue

from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import ProviderError, SpecError
from harnessweaver.core.messages import ModelRequest, ModelResponse, StreamChunk
from harnessweaver.core.ports import ModelProvider, StreamingModelProvider

__all__ = ["Cassette", "request_digest"]

FORMAT_VERSION: Final = 1

type Mode = Literal["replay", "record", "auto"]


def request_digest(request: ModelRequest) -> str:
    """What identifies a request in a cassette. Request metadata is not part of it."""
    body = request.model_dump(mode="json", exclude={"metadata"})
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("ascii")).hexdigest()


class Cassette:
    """A model provider that replays recorded answers, or records them from ``provider``.

    Args:
        path: The cassette file (JSON).
        provider: The real provider to record from; not needed to replay.
        mode: ``replay`` never calls out; ``record`` always calls out and overwrites;
            ``auto`` replays if the file exists, otherwise records.
        scrub: Applied to every recorded answer before it is saved (S7).

    Raises:
        SpecError: When recording is needed but no provider was given.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        provider: ModelProvider | None = None,
        mode: Mode = "auto",
        scrub: Callable[[ModelResponse], ModelResponse] | None = None,
    ) -> None:
        self.path = Path(path)
        self.provider = provider
        self.scrub = scrub
        self.recording = mode == "record" or (mode == "auto" and not self.path.exists())
        if self.recording and provider is None:
            raise SpecError(f"cassette {self.path} needs a provider to record from")
        self.interactions: list[dict[str, JsonValue]] = [] if self.recording else self._read()
        self._used: set[int] = set()

    def _read(self) -> list[dict[str, JsonValue]]:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SpecError(f"no cassette at {self.path}; record it first") from None
        if document.get("version") != FORMAT_VERSION:
            raise SpecError(
                f"cassette {self.path} has format {document.get('version')!r}, not {FORMAT_VERSION}"
            )
        return list(document["interactions"])

    def save(self) -> None:
        """Write the cassette (recording mode saves after every answer)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {"version": FORMAT_VERSION, "interactions": self.interactions}
        self.path.write_text(
            json.dumps(body, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="ascii"
        )

    def _replay(self, request: ModelRequest) -> dict[str, JsonValue]:
        digest = request_digest(request)
        for index, interaction in enumerate(self.interactions):
            if index not in self._used and interaction.get("digest") == digest:
                self._used.add(index)
                return interaction
        raise ProviderError(
            f"cassette {self.path.name} has no recorded answer for this request; re-record it"
        )

    async def _record(
        self, request: ModelRequest, response: ModelResponse, chunks: list[str] | None
    ) -> None:
        if self.scrub is not None:
            response = self.scrub(response)
        entry: dict[str, JsonValue] = {
            "digest": request_digest(request),
            "model": request.model or request.alias,
            "response": response.model_dump(mode="json"),
        }
        if chunks is not None:
            entry["chunks"] = list[JsonValue](chunks)
        self.interactions.append(entry)
        await anyio.to_thread.run_sync(self.save)

    async def generate(self, request: ModelRequest, env: Envelope) -> ModelResponse:
        if not self.recording:
            return ModelResponse.model_validate(self._replay(request)["response"])
        assert self.provider is not None
        response = await self.provider.generate(request, env)
        await self._record(request, response, None)
        return self.scrub(response) if self.scrub is not None else response

    async def stream(
        self, request: ModelRequest, env: Envelope
    ) -> AsyncIterator[StreamChunk | ModelResponse]:
        if not self.recording:
            interaction = self._replay(request)
            response = ModelResponse.model_validate(interaction["response"])
            raw: Any = interaction.get("chunks") or [response.text]
            for index, delta in enumerate(raw):
                yield StreamChunk(index=index, delta=str(delta))
            yield response
            return
        assert self.provider is not None
        if not isinstance(self.provider, StreamingModelProvider):
            response = await self.provider.generate(request, env)
            await self._record(request, response, None)
            yield StreamChunk(index=0, delta=response.text)
            yield response
            return
        deltas: list[str] = []
        final: ModelResponse | None = None
        async for item in self.provider.stream(request, env):
            if isinstance(item, ModelResponse):
                final = item
            else:
                deltas.append(item.delta)
                yield item
        final = final or ModelResponse(text="".join(deltas))
        await self._record(request, final, deltas)
        yield final
