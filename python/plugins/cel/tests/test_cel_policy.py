"""cel.policy: the shared policy fixtures, and where full CEL and cel-lite differ (R11)."""

import json
import math
from pathlib import Path
from typing import Any

import pytest

import harnessweaver as hw
from harnessweaver.core.registry import PluginCatalog, PluginSource
from harnessweaver.errors import SpecError
from harnessweaver_cel import CelPolicy

FIXTURES = Path(__file__).resolve().parents[4] / "contracts" / "fixtures" / "conformance"
CATALOG = PluginCatalog([PluginSource("cel", "harnessweaver_cel:plugin", "entry_point")])

# Where cel-python 0.5 and cel-lite answer the shared expr fixtures differently. Each
# entry says why; a new difference fails the test until it is understood and listed.
RELAXATION = "cel-lite relaxation: ints and doubles mix (ADR-0004)"
CEL_PYTHON = "cel-python 0.5 departs from the CEL spec here"
LITE_SUBSET = "outside the cel-lite subset"
KNOWN_DIFFERENCES = {
    "mixed int and double gives a double": RELAXATION,
    "int and double compare": RELAXATION,
    "numeric equality across types": RELAXATION,
    "integral float in data acts as an int": RELAXATION,
    "different types are not equal": RELAXATION,
    "bool and int are different map keys": RELAXATION,
    "negative index": CEL_PYTHON,
    "has needs a field selection": CEL_PYTHON,
    "string of an integral double": CEL_PYTHON,
    "string of a tiny double": CEL_PYTHON,
    "string of a small double": CEL_PYTHON,
    "string of a bool": CEL_PYTHON,
    "int of a bool": CEL_PYTHON,
    "or needs bools": CEL_PYTHON,
    "predicate must be a bool": CEL_PYTHON,
    "macro needs a list or map": CEL_PYTHON,
    "invalid escape": CEL_PYTHON,
    "trailing comma in list": LITE_SUBSET,
    "unsigned suffix": LITE_SUBSET,
    "triple-quoted string": LITE_SUBSET,
}


def _cases(suite: str) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted((FIXTURES / suite).glob("*.json")):
        cases += json.loads(path.read_text(encoding="utf-8"))["cases"]
    return cases


def _plain(value: Any) -> Any:
    from celpy import celtypes

    if isinstance(value, celtypes.BoolType):
        return bool(value)
    if isinstance(value, celtypes.IntType | celtypes.UintType):
        return int(value)
    if isinstance(value, celtypes.DoubleType):
        return float(value)
    if isinstance(value, celtypes.StringType):
        return str(value)
    if isinstance(value, celtypes.ListType):
        return [_plain(item) for item in value]
    if isinstance(value, celtypes.MapType):
        return {_plain(key): _plain(item) for key, item in value.items()}
    return value


def _cel(case: dict[str, Any]) -> tuple[str, Any]:
    import celpy
    from celpy.adapter import json_to_cel
    from celpy.evaluation import CELEvalError

    environment = celpy.Environment()
    try:
        program = environment.program(environment.compile(case["expr"]))
        result = program.evaluate({k: json_to_cel(v) for k, v in case.get("vars", {}).items()})
    except Exception:  # syntax, evaluation or a crash inside cel-python: not a value
        return ("error", None)
    if isinstance(result, CELEvalError):
        return ("error", None)
    return ("value", _plain(result))


def _agrees(case: dict[str, Any]) -> bool:
    expect = case["expect"]
    kind, got = _cel(case)
    if "value" not in expect:
        return kind == "error"
    want = expect["value"]
    if kind != "value":
        return False
    if isinstance(got, float) and isinstance(want, int | float) and not isinstance(want, bool):
        return math.isclose(got, want) and expect.get("type") != "int"
    return got == want


def test_full_cel_agrees_with_cel_lite_except_where_listed() -> None:
    cases = _cases("expr")
    differing = {case["name"] for case in cases if not _agrees(case)}
    assert differing == set(KNOWN_DIFFERENCES)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case", [c for c in _cases("governor") if "rules" in c], ids=lambda c: c["name"]
)
async def test_the_shared_policy_fixtures(case: dict[str, Any]) -> None:
    config = hw.PolicyConfig(rules=case["rules"], default_effect=case["default_effect"])
    decision = await CelPolicy(config).decide(hw.PolicyRequest.model_validate(case["request"]))
    assert (decision.effect.value, decision.rule) == (
        case["expect"]["effect"],
        case["expect"]["rule"],
    )


def test_a_rule_that_isnt_cel_fails_at_load() -> None:
    config = hw.PolicyConfig.model_validate(
        {"rules": [{"id": "x", "when": "args.amount >", "effect": "deny"}]}
    )
    with pytest.raises(SpecError, match=r"policy.rules\[x\].when isn't valid CEL"):
        CelPolicy(config)


@pytest.mark.anyio
async def test_a_harness_uses_it_by_name(tmp_path: Path) -> None:
    rules = [
        {
            "id": "contractors",
            "when": "principal.roles.exists(r, r == 'contractor')",
            "effect": "deny",
            "hook": "run.start",
        }
    ]
    document = {
        "apiVersion": "harnessweaver/v1",
        "kind": "Harness",
        "metadata": {"name": "cel-app"},
        "policy": {"use": "cel.policy", "rules": rules},
    }
    path = tmp_path / "harness.yaml"
    path.write_text(json.dumps(document), encoding="ascii")
    harness = hw.Harness.load(path, catalog=CATALOG)
    with pytest.raises(hw.errors.RunBlocked, match="contractors"):
        async with harness.session(principal=hw.Principal(id="carl", roles=("contractor",))):
            pass
    async with harness.session(principal="alice"):
        pass
