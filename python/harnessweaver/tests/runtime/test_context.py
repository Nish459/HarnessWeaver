"""Context sources, memory and citation checks in running harnesses (DESIGNS No. 21)."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.errors import SpecError, ValidationFailed

from .conftest import Builder, spec

pytestmark = pytest.mark.anyio

DOCUMENTS = [
    {"id": "kb-1", "content": "Refunds take five business days.", "acl": {"tenants": ["acme"]}},
    {
        "id": "kb-2",
        "content": "Refunds over 500 dollars need a manager.",
        "acl": {"tenants": ["acme"]},
    },
    {"id": "gx-1", "content": "Globex refunds are instant.", "acl": {"tenants": ["globex"]}},
    {"id": "pub-1", "content": "Our offices close at five."},
]


def with_context(build: Builder, **sources: dict[str, Any]) -> hw.Harness:
    models = {"provider": "testkit.scripted", "replies": [{"text": "x"}]}
    return build(spec(models=models, context=sources))


def drops(session: hw.Session) -> list[tuple[str | None, str]]:
    return [
        (e.code, str(e.details["item"]))
        for e in session.trace.events
        if e.source == "harness.context"
    ]


async def test_a_memory_source_finds_what_the_tenant_may_see(build: Builder, testkit: Any) -> None:
    harness = with_context(build, kb={"use": "memory", "documents": DOCUMENTS})
    async with harness.session(tenant="acme") as s:
        items = await s.context("kb").fetch("how long do refunds take")
        assert s.envelope.labels.untrusted_seen
    assert [i.id for i in items] == ["kb-1", "kb-2"]
    assert all(i.source == "kb" and i.untrusted for i in items)
    assert items[0].score is not None
    async with harness.session(tenant="globex") as s:
        assert [i.id for i in await s.context("kb").fetch("refunds")] == ["gx-1"]


async def test_documents_can_live_in_a_file(build: Builder, tmp_path: Path, testkit: Any) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "kb.yaml").write_text(
        json.dumps({"documents": DOCUMENTS}), encoding="ascii"
    )
    harness = with_context(build, kb={"use": "memory", "file": "data/kb.yaml", "label": "trusted"})
    async with harness.session(tenant="acme") as s:
        items = await s.context("kb").fetch("offices close")
        assert not s.envelope.labels.untrusted_seen  # a trusted source doesn't taint the run
    assert [(i.id, i.untrusted) for i in items] == [("pub-1", False)]


async def test_a_leaky_provider_cant_leak_across_tenants(build: Builder, testkit: Any) -> None:
    harness = with_context(build, kb={"use": "testkit.leaky"})
    async with harness.session(tenant="acme") as s:
        items = await s.context("kb").fetch("refunds")
        dropped = drops(s)
        trace = json.dumps([e.model_dump(mode="json") for e in s.trace.events])
    assert [i.id for i in items] == ["acme-1", "open-1"]
    assert dropped == [("context_acl", "globex-1")]
    assert "Globex secret" not in trace  # drops name the item, never its content (R9)
    strict = with_context(build, kb={"use": "testkit.leaky", "require_acl": True})
    async with strict.session(tenant="acme") as s:
        assert [i.id for i in await s.context("kb").fetch("refunds")] == ["acme-1"]
        assert drops(s) == [("context_acl", "globex-1"), ("context_acl", "open-1")]


@pytest.mark.parametrize(
    ("caps", "kept", "dropped"),
    [
        ({"max_items": 1}, ["kb-1"], []),  # the provider is asked for one item
        ({"max_tokens": 9}, ["kb-1"], ["kb-2"]),
    ],
)
async def test_caps_hold_and_every_drop_is_traced(
    build: Builder, testkit: Any, caps: dict[str, int], kept: list[str], dropped: list[str]
) -> None:
    harness = with_context(build, kb={"use": "memory", "documents": DOCUMENTS, **caps})
    async with harness.session(tenant="acme") as s:
        items = await s.context("kb").fetch("refunds")
        assert [i.id for i in items] == kept
        assert [item for code, item in drops(s) if code == "context_cap"] == dropped


async def test_items_the_app_retrieved_are_governed_too(build: Builder, testkit: Any) -> None:
    harness = with_context(build, kb={"use": "passthrough", "max_items": 1})
    mine = hw.ContextItem(id="a", content="x", source="app", untrusted=False)
    theirs = hw.ContextItem(id="b", content="y", source="app", acl=hw.Acl(tenants=("globex",)))
    extra = hw.ContextItem(id="c", content="z", source="app")
    async with harness.session(tenant="acme") as s:
        assert await s.context("kb").fetch("anything") == ()
        kept = await s.context("kb").check([mine, theirs, extra])
        assert [(i.id, i.source, i.untrusted) for i in kept] == [("a", "kb", True)]
        assert drops(s) == [("context_acl", "b"), ("context_cap", "c")]
        with pytest.raises(SpecError, match="no context source 'docs'"):
            await s.context("docs").fetch("anything")


async def test_memory_is_namespaced_and_expires(build: Builder, testkit: Any) -> None:
    clock = hw.FakeClock()
    models = {"provider": "testkit.scripted", "replies": [{"text": "x"}]}
    harness = build(spec(models=models, memory={"default_ttl": "1h"}), clock=clock)
    async with harness.session(principal="alice", tenant="acme") as s:
        await s.memory.put("tone", "formal")
        await s.memory.put("plan", {"tier": "gold"}, ttl=timedelta(days=30))
        assert await s.memory.get("tone") == "formal"
        assert s.memory.namespace == ("acme", "alice", "")
    for principal, tenant in (("bob", "acme"), ("alice", "globex")):
        async with harness.session(principal=principal, tenant=tenant) as s:
            assert await s.memory.entries() == {}
    clock.advance(timedelta(hours=2))
    async with harness.session(principal="alice", tenant="acme") as s:
        assert await s.memory.get("tone") is None
        assert await s.memory.entries() == {"plan": {"tier": "gold"}}
        await s.memory.delete("plan")
        assert await s.memory.entries() == {}


async def test_citations_must_name_what_the_run_retrieved(build: Builder, testkit: Any) -> None:
    models = {"provider": "testkit.scripted", "replies": [{"text": "x"}]}
    document = spec(
        models=models,
        context={"kb": {"use": "memory", "documents": DOCUMENTS}},
        guardrails={"output": [{"id": "grounded", "use": "grounded.citations"}]},
    )
    harness = build(document)
    async with harness.session(tenant="acme") as s:
        await s.context("kb").fetch("refund days")
        good = "Refunds take five business days [kb-1]."
        assert await s.validate("output", good) == good
        with pytest.raises(ValidationFailed, match="name nothing the run retrieved"):
            await s.validate("output", "Globex refunds are instant for everyone [gx-1].")


async def test_kept_context_survives_a_suspension(build: Builder, testkit: Any) -> None:
    document = spec(
        models={"provider": "testkit.scripted", "replies": [{"text": "x"}]},
        context={"kb": {"use": "memory", "documents": DOCUMENTS}},
        tasks={
            "t": {
                "runner": {"use": "session", "handler": "hw_testkit:cite_then_refund"},
                "approvals": {"tools": ["refund"]},
            }
        },
    )
    harness = build(document)
    waiting = await harness.run("t", {}, tenant="acme")
    assert waiting.status is hw.RunStatus.AWAITING_APPROVAL
    checkpoint = await harness._state.get_checkpoint(waiting.run_id)  # pyright: ignore[reportPrivateUsage]
    assert checkpoint is not None
    assert checkpoint.context_ids == ("kb-1", "kb-2")
    assert waiting.approval is not None
    done = await harness.approve(
        waiting.run_id, waiting.approval.approval_id, approver=hw.Principal(id="bob")
    )
    assert done.ok, done.error
    assert done.output == {"cited": ["kb-1", "kb-2"]}
