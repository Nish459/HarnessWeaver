"""Routing cascades in running harnesses (DESIGNS No. 19, ADR-0029)."""

import json
from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.errors import SpecError, UnknownProvider
from harnessweaver.testing import FakeDecider, harness_for_test, output, scripted

from .conftest import Builder, spec

pytestmark = pytest.mark.anyio

OPTIONS = ["billing", "smalltalk", "other"]
UTTERANCES = {"billing": ["refund my order", "charged twice"], "smalltalk": ["hello there"]}


def router(*cascade: dict[str, Any], default: str | None = "other") -> dict[str, Any]:
    return {"support": {"options": OPTIONS, "cascade": list(cascade), "default": default}}


def routed(build: Builder, routing: dict[str, Any], *replies: dict[str, Any]) -> hw.Harness:
    models = {"provider": "testkit.scripted", "replies": list(replies) or [{"text": "x"}]}
    return build(spec(models=models, routing=routing))


def stage_notes(session: hw.Session) -> list[tuple[str, bool]]:
    return [
        (str(e.details["stage"]), bool(e.details["won"]))
        for e in session.trace.events
        if e.source == "harness.routing"
    ]


async def test_the_first_confident_stage_wins_and_every_stage_is_traced(
    build: Builder, tmp_path: Path, testkit: Any
) -> None:
    (tmp_path / "routes").mkdir()
    rules = {"rules": [{"id": "refunds", "when": "text.contains('refund')", "choice": "billing"}]}
    (tmp_path / "routes" / "support.rules.yaml").write_text(json.dumps(rules), encoding="ascii")
    harness = routed(
        build,
        router(
            {"use": "rules", "file": "routes/support.rules.yaml"},
            {"use": "lexical", "utterances": UTTERANCES, "threshold": 0.6},
        ),
    )
    async with harness.session() as s:
        exact = await s.decide("support", text="I need a refund")
        lexical = await s.decide("support", text="hello")
        fallback = await s.decide("support", text="what is the weather")
        notes = stage_notes(s)
    assert (exact.kind, exact.choice, exact.stage) == (hw.DecisionKind.EXACT, "billing", "rules#1")
    assert (lexical.choice, lexical.stage) == ("smalltalk", "lexical#1")
    assert lexical.confidence == pytest.approx(0.707107)
    assert (fallback.kind, fallback.choice) == (hw.DecisionKind.DEFAULT, "other")
    assert notes == [
        ("rules#1", True),  # stages without an id get <use>#<n>, like guards
        ("rules#1", False),
        ("lexical#1", True),
        ("rules#1", False),
        ("lexical#1", False),
    ]
    trace = json.dumps([e.model_dump(mode="json") for e in s.trace.events])
    assert "weather" not in trace  # stage reasons never quote the text (R9)


async def test_the_llm_stage_is_governed_and_thresholded(build: Builder, testkit: Any) -> None:
    sure = {"output": {"choice": "billing", "confidence": 0.9}}
    unsure = {"output": {"choice": "billing", "confidence": 0.4}}
    harness = routed(build, router({"use": "llm", "threshold": 0.7}), sure, unsure)
    async with harness.session() as s:
        first = await s.decide("support", text="my card was charged")
        second = await s.decide("support", text="my card was charged")
    assert (first.choice, first.stage, first.confidence) == ("billing", "llm#1", 0.9)
    assert (second.kind, second.choice) == (hw.DecisionKind.DEFAULT, "other")
    sent = testkit.RECORDER.requests[0]
    assert sent.output_schema["properties"]["choice"]["enum"] == [*OPTIONS, "none"]
    assert s.envelope.budget is not None  # the stage's calls went through the meter


async def test_a_custom_decider_and_the_semantic_stage(build: Builder, testkit: Any) -> None:
    harness = routed(
        build,
        router(
            {"use": "testkit.vip"},
            {"use": "semantic", "utterances": UTTERANCES, "threshold": 0.6},
        ),
    )
    async with harness.session() as s:
        vip = await s.decide("support", text="anything", state={"tier": "vip"})
        semantic = await s.decide("support", text="refund the order")
    assert (vip.choice, vip.stage, vip.reason) == ("billing", "testkit.vip#1", "vip customer")
    assert (semantic.choice, semantic.stage) == ("billing", "semantic#1")
    assert semantic.confidence == pytest.approx(0.697863)


async def test_a_router_answers_only_its_own_requests_and_options(
    build: Builder, testkit: Any
) -> None:
    harness = routed(build, router({"use": "lexical", "utterances": UTTERANCES}, default=None))
    async with harness.session() as s:
        other = await s.decide("intake", text="refund my order")
        narrowed = await s.decide("support", text="refund my order", options=["smalltalk"])
    assert other.kind is hw.DecisionKind.ABSTAIN
    assert narrowed.kind is hw.DecisionKind.ABSTAIN  # billing isn't on offer this time


@pytest.mark.parametrize(
    ("cascade", "error", "message"),
    [
        ({"use": "lexical", "utterances": {"refunds": ["x"]}}, SpecError, "refunds isn't one of"),
        (
            {"use": "rules", "rules": [{"when": "text ==", "choice": "billing"}]},
            SpecError,
            "routing rule",
        ),
        ({"use": "rules", "file": "routes/missing.yaml"}, SpecError, "missing.yaml"),
        ({"use": "lexical"}, SpecError, "needs utterances"),
        ({"use": "nope"}, UnknownProvider, "nope"),
        (
            {"use": "semantic", "utterances": UTTERANCES, "encoder": "acme.embed"},
            UnknownProvider,
            "acme",
        ),
    ],
)
async def test_bad_cascades_fail_to_load(
    build: Builder, testkit: Any, cascade: dict[str, Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        routed(build, router(cascade))


async def test_fake_deciders_still_stand_in_for_routing() -> None:
    decider = FakeDecider("billing", confidence=0.8)
    harness = harness_for_test(model=scripted(output({})), deciders={"support": decider})
    async with harness.session() as s:
        decision = await s.decide("support", text="refund", options=OPTIONS)
    assert (decision.choice, decision.confidence) == ("billing", 0.8)
    assert decider.requests[0].text == "refund"
