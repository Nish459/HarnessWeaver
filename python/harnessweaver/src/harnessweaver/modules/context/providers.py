"""The built-in context providers: ``passthrough`` and ``memory`` (DESIGNS No. 21)."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from harnessweaver.core.envelope import Envelope
from harnessweaver.core.errors import SpecError
from harnessweaver.core.plugins import provider
from harnessweaver.core.retrieval import Acl, ContextItem
from harnessweaver.core.text import lexical_similarity
from harnessweaver.spec.yaml import load_yaml_file

__all__ = ["Document", "MemoryContext", "MemoryContextConfig", "PassthroughContext"]


@provider(port="ContextProvider", name="passthrough", deterministic=True, latency_class="fast")
class PassthroughContext:
    """For items the app retrieves itself and passes to ``s.context(name).check(items)``:
    the source gets governance (ACLs, labels, caps), and fetching returns nothing."""

    async def fetch(
        self, query: str, env: Envelope, *, limit: int | None = None
    ) -> list[ContextItem]:
        return []


class Document(BaseModel):
    """One document of the ``memory`` provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    content: str
    acl: Acl | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class MemoryContextConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    documents: tuple[Document, ...] = ()
    file: str | None = Field(default=None, description="A YAML file with a 'documents' list.")


@provider(
    port="ContextProvider",
    name="memory",
    config=MemoryContextConfig,
    deterministic=True,
    latency_class="fast",
    sample={"documents": [{"id": "kb-1", "content": "Refunds take five days."}]},
)
class MemoryContext:
    """Documents held in memory, searched lexically (token cosine, ADR-0029). Like every
    provider, it returns only what the envelope's tenant and principal may see.

    Raises:
        SpecError: At construction, for a missing or malformed documents file.
    """

    def __init__(self, config: MemoryContextConfig) -> None:
        documents = list(config.documents)
        if config.file is not None:
            loaded = load_yaml_file(Path(config.file))
            if not isinstance(loaded, dict) or not isinstance(loaded.get("documents"), list):  # pyright: ignore[reportUnknownMemberType]
                raise SpecError(f"{config.file} must be a map with a 'documents' list")
            documents += [Document.model_validate(d) for d in loaded["documents"]]  # pyright: ignore[reportUnknownVariableType]
        ids = [d.id for d in documents]
        if len(ids) != len(set(ids)):
            raise SpecError("context documents must have unique ids")
        self.documents = documents

    async def fetch(
        self, query: str, env: Envelope, *, limit: int | None = None
    ) -> list[ContextItem]:
        scored = [
            (lexical_similarity(query, document.content), document)
            for document in self.documents
            if document.acl is None or document.acl.allows(env.tenant, env.principal)
        ]
        ranked = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1].id))
        return [
            ContextItem(
                id=document.id,
                content=document.content,
                source="memory",
                score=round(score, 6),
                acl=document.acl,
                metadata=document.metadata,
            )
            for score, document in ranked[:limit]
        ]
