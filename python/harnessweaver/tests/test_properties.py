"""Hypothesis property tests for outcome, expression, duration and version logic (RULES T3)."""

from datetime import timedelta

from hypothesis import given
from hypothesis import strategies as st

from harnessweaver import Block, Continue, Escalate, PolicyEffect, Retry, Suspend, tighten
from harnessweaver.core.durations import duration_ms, format_duration, parse_duration
from harnessweaver.core.expr import compile_expression
from harnessweaver.core.outcomes import Outcome, most_severe, severity
from harnessweaver.core.semver import Version, VersionRange

reasons = st.text(min_size=1, max_size=5)
outcomes: st.SearchStrategy[Outcome] = st.one_of(
    st.just(Continue()),
    st.builds(Continue, modified=st.integers()),
    st.builds(Retry, reason=reasons),
    st.builds(Escalate, reason=reasons),
    st.builds(Suspend, reason=reasons),
    st.builds(Block, reason=reasons),
)


@given(st.lists(outcomes, max_size=8))
def test_most_severe_has_the_maximum_severity(items: list[Outcome]) -> None:
    result = most_severe(items)
    assert severity(result) == max((severity(o) for o in items), default=0)
    if items:
        assert any(result is o for o in items)


@given(st.lists(outcomes, max_size=8), st.randoms())
def test_combined_severity_ignores_order(items: list[Outcome], rng: object) -> None:
    shuffled = list(items)
    rng.shuffle(shuffled)  # type: ignore[attr-defined]
    assert severity(most_severe(items)) == severity(most_severe(shuffled))


@given(st.sampled_from(list(PolicyEffect)), st.sampled_from(list(PolicyEffect)))
def test_tighten_is_monotonic(current: PolicyEffect, proposed: PolicyEffect) -> None:
    result = tighten(current, proposed)
    assert result.rank == max(current.rank, proposed.rank)
    assert result.rank >= current.rank


@given(st.integers(min_value=0, max_value=10**12))
def test_durations_round_trip(ms: int) -> None:
    text = format_duration(timedelta(milliseconds=ms))
    assert duration_ms(parse_duration(text)) == ms


versions = st.builds(
    Version,
    st.integers(0, 50),
    st.integers(0, 50),
    st.integers(0, 50),
    st.lists(
        st.one_of(st.integers(0, 20), st.sampled_from(["alpha", "beta", "rc"])), max_size=3
    ).map(tuple),
)


@given(versions)
def test_versions_round_trip(version: Version) -> None:
    assert Version.parse(str(version)) == version


@given(versions, versions)
def test_version_order_is_antisymmetric(a: Version, b: Version) -> None:
    assert (a < b) + (a == b) + (a > b) == 1


@given(versions)
def test_caret_contains_its_release_and_excludes_the_next_major(version: Version) -> None:
    release = Version(version.major, version.minor, version.patch)
    caret = VersionRange.parse(f"^{release}")
    assert caret.contains(release)
    assert not caret.contains(Version(version.major + 1, 0, 0))


small_ints = st.integers(min_value=-(10**6), max_value=10**6)


@given(small_ints, small_ints)
def test_int_arithmetic_matches_cel(a: int, b: int) -> None:
    variables = {"a": a, "b": b}
    assert compile_expression("a + b").evaluate(variables) == a + b
    assert compile_expression("a - b").evaluate(variables) == a - b
    assert compile_expression("a * b").evaluate(variables) == a * b
    if b != 0:
        quotient = compile_expression("a / b").evaluate(variables)
        remainder = compile_expression("a % b").evaluate(variables)
        assert isinstance(quotient, int)
        assert isinstance(remainder, int)
        assert quotient * b + remainder == a  # truncated division identity
        assert abs(remainder) < abs(b)


@given(st.booleans(), st.booleans())
def test_de_morgan(x: bool, y: bool) -> None:
    variables = {"x": x, "y": y}
    assert compile_expression("!(x && y) == (!x || !y)").evaluate_bool(variables)
    assert compile_expression("!(x || y) == (!x && !y)").evaluate_bool(variables)


json_values = st.recursive(
    st.none() | st.booleans() | small_ints | st.text(max_size=5),
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=3), children, max_size=3)
    ),
    max_leaves=10,
)


@given(json_values)
def test_values_equal_themselves_and_are_members_of_their_list(value: object) -> None:
    variables = {"v": value}
    assert compile_expression("v == v").evaluate_bool(variables)
    assert compile_expression("v in [v]").evaluate_bool(variables)
