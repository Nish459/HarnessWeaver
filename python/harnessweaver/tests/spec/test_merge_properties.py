"""Hypothesis properties of the merge rules (RULES T3)."""

from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from harnessweaver.core.errors import BoundViolation, LockViolation
from harnessweaver.spec.merge import Layer, LayerKind, merge_layers

keys = st.sampled_from(["a", "b", "c", "d"])
scalars = st.one_of(st.integers(-5, 5), st.sampled_from(["x", "y"]), st.booleans())


@given(st.dictionaries(keys, scalars, min_size=1), st.data())
def test_locked_values_never_change(org: dict[str, Any], data: st.DataObject) -> None:
    locked = data.draw(st.lists(st.sampled_from(sorted(org)), unique=True))
    app = data.draw(st.dictionaries(keys, scalars))
    layers = [
        Layer("org", LayerKind.ORG, {"x": org, "locks": [f"x.{k}" for k in locked]}),
        Layer("app", LayerKind.APP, {"x": app}),
    ]
    changes_locked = any(
        k in app and (app[k] != org[k] or type(app[k]) is not type(org[k])) for k in locked
    )
    if changes_locked:
        with pytest.raises(LockViolation):
            merge_layers(layers)
        return
    merged = merge_layers(layers).data["x"]
    for key in locked:
        assert merged[key] == org[key]
    for key, value in app.items():
        assert merged[key] == value


ids = st.lists(st.sampled_from(list("abcdefg")), unique=True)


@given(ids, ids)
def test_keyed_lists_keep_earlier_items_in_order(base: list[str], app: list[str]) -> None:
    layers = [
        Layer(
            "org", LayerKind.ORG, {"guardrails": {"input": [{"id": i, "use": "u"} for i in base]}}
        ),
        Layer(
            "app", LayerKind.APP, {"guardrails": {"input": [{"id": i, "use": "u"} for i in app]}}
        ),
    ]
    merged = [
        item["id"] for item in merge_layers(layers).data.get("guardrails", {}).get("input", [])
    ]
    assert merged == base + [i for i in app if i not in base]


@given(st.floats(0, 100, allow_nan=False), st.floats(0, 100, allow_nan=False))
def test_bounds_never_clamp(value: float, maximum: float) -> None:
    layers = [
        Layer("org", LayerKind.ORG, {"bounds": {"budgets.per_run.max_usd": {"max": maximum}}}),
        Layer("app", LayerKind.APP, {"budgets": {"per_run": {"max_usd": value}}}),
    ]
    if value > maximum:
        with pytest.raises(BoundViolation):
            merge_layers(layers)
    else:
        assert merge_layers(layers).data["budgets"]["per_run"]["max_usd"] == value


maps = st.recursive(
    scalars, lambda inner: st.dictionaries(keys, inner, max_size=3), max_leaves=8
).filter(lambda v: isinstance(v, dict))


def _consistent(*maps: dict[str, Any]) -> bool:
    """No key is a map in one layer and a scalar in another (replacement is order-dependent)."""
    for key in {k for m in maps for k in m}:
        values = [m[key] for m in maps if key in m]
        nested = [isinstance(v, dict) for v in values]
        if any(nested) and not all(nested):
            return False
        if all(nested) and not _consistent(*values):
            return False
    return True


@given(maps, maps, maps)
def test_merging_maps_is_associative(
    a: dict[str, Any], b: dict[str, Any], c: dict[str, Any]
) -> None:
    assume(_consistent(a, b, c))

    def merge(*bodies: dict[str, Any]) -> dict[str, Any]:
        return merge_layers(
            [Layer(f"l{i}", LayerKind.APP, {"x": body}) for i, body in enumerate(bodies)]
        ).data

    assert merge(merge(a, b)["x"], c) == merge(a, merge(b, c)["x"])
