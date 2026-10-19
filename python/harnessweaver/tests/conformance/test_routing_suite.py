"""Runner for the ``routing`` fixtures: tokens, similarity, embeddings, stages, the cascade."""

from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.text import cosine, hashing_embedding, lexical_similarity, tokens
from harnessweaver.modules.routing import LexicalDecider, RulesDecider, Stage, decide_in_cascade
from harnessweaver.modules.routing.stages import LexicalConfig, RulesConfig

pytestmark = [pytest.mark.conformance_suite("routing"), pytest.mark.anyio]


def _shape(decision: hw.Decision | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    confidence = None if decision.confidence is None else round(decision.confidence, 6)
    return {"kind": decision.kind.value, "choice": decision.choice, "confidence": confidence}


class _Answer:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec

    async def __call__(self, request: hw.DecisionRequest) -> hw.Decision:
        if self.spec.get("error"):
            raise RuntimeError("stage down")
        return hw.Decision.model_validate(self.spec["answer"])


async def test_routing(case: dict[str, Any]) -> None:
    expect = case["expect"]
    if "tokens" in case:
        assert tokens(case["tokens"]) == expect["tokens"]
    elif "embed" in case:
        vector = hashing_embedding(case["embed"], case["dims"])
        assert [round(v, 6) for v in vector] == expect["vector"]
    elif "cosine" in expect:
        a, b = (hashing_embedding(case[k], case["dims"]) for k in ("a", "b"))
        assert round(cosine(a, b), 6) == expect["cosine"]
    elif "similarity" in expect:
        assert round(lexical_similarity(case["a"], case["b"]), 6) == expect["similarity"]
    elif "stage" in case:
        if case["stage"] == "rules":
            decider: Any = RulesDecider(RulesConfig.model_validate(case["config"]))
        else:
            decider = LexicalDecider(LexicalConfig.model_validate(case["config"]))
        decision = await decider(hw.DecisionRequest.model_validate(case["request"]))
        assert _shape(decision) == expect
    else:
        stages = [
            Stage(label=f"s{i + 1}", decider=_Answer(spec), threshold=spec.get("threshold"))
            for i, spec in enumerate(case["stages"])
        ]
        won: list[bool] = []

        def note(router: str, stage: Stage, decision: hw.Decision, winner: bool) -> None:
            won.append(winner)

        async def ask(decider: Any) -> hw.Decision:
            return await decider(hw.DecisionRequest(router="r", options=tuple(case["options"])))

        decision = await decide_in_cascade("r", stages, case["options"], case["default"], ask, note)
        got = (
            None
            if decision is None
            else {"kind": decision.kind.value, "choice": decision.choice, "stage": decision.stage}
        )
        assert got == expect["decision"]
        assert won == expect["won"]
