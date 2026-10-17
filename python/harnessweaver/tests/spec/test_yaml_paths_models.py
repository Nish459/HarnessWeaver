import pytest
from pydantic import ValidationError

from harnessweaver.core.errors import SpecError
from harnessweaver.spec.models import EvalsSpec, GuardSpec, HarnessSpec, RouterSpec, TaskSpec
from harnessweaver.spec.paths import Item, format_path, is_prefix, matches, parse_path
from harnessweaver.spec.sources import BuiltinProfiles, parse_ref
from harnessweaver.spec.yaml import load_yaml


def test_yaml_uses_the_1_2_core_schema() -> None:
    data = load_yaml(
        "a: no\nb: on\nc: 1:30\nd: 2026-01-05\ne: True\nf: ~\ng:\n"
        "h: 0x1F\ni: 0o17\nj: 012\nk: 1.5e3\n"
    )
    assert data == {
        "a": "no", "b": "on", "c": "1:30", "d": "2026-01-05", "e": True,
        "f": None, "g": None, "h": 31, "i": 15, "j": 12, "k": 1500.0,
    }  # fmt: skip


def test_yaml_rejects_duplicate_keys_and_bad_syntax() -> None:
    with pytest.raises(SpecError, match="duplicate key 'a'"):
        load_yaml("a: 1\na: 2\n")
    with pytest.raises(SpecError, match="invalid YAML"):
        load_yaml("a: [1, 2\n")


def test_paths_round_trip() -> None:
    path = parse_path("guardrails.input[pii.regex#1].action")
    assert path == ("guardrails", "input", Item("pii.regex#1"), "action")
    assert format_path(path) == "guardrails.input[pii.regex#1].action"
    assert is_prefix(parse_path("guardrails.input"), path)
    assert matches(parse_path("guardrails.*[*].action"), path)
    assert not matches(parse_path("guardrails.*"), path)


@pytest.mark.parametrize("text", ["", "a.", ".a", "a[]", "a[x", "a..b", "a]"])
def test_malformed_paths(text: str) -> None:
    with pytest.raises(ValueError, match="invalid spec path"):
        parse_path(text)


def test_spec_models() -> None:
    with pytest.raises(ValidationError, match="not one of the options"):
        RouterSpec(options=("a",), default="b")
    with pytest.raises(ValidationError, match="must be a list of dataset files"):
        EvalsSpec.model_validate({"task": "evals/a.yaml"})
    assert EvalsSpec.model_validate(
        {"task": ["a.yaml"], "online": {"sample_rate": 0.1}}
    ).suites() == {"task": ("a.yaml",)}
    assert TaskSpec.model_validate({"runner": "session"}).runner.use == "session"
    guard = GuardSpec.model_validate({"use": "pii.regex", "entities": ["EMAIL"]})
    assert guard.provider_settings() == {"entities": ["EMAIL"]}
    with pytest.raises(ValidationError):
        HarnessSpec.model_validate({"metadata": {"name": "a"}, "surprise": 1})
    with pytest.raises(ValidationError):
        HarnessSpec.model_validate({"metadata": {"name": "Not Valid"}})


@pytest.mark.parametrize("name", ["defaults", "extraction", "rag", "agent", "workflow", "chat"])
def test_builtin_profiles_resolve(name: str) -> None:
    resolved = BuiltinProfiles().resolve(parse_ref(f"profile://{name}@^1"), None)
    assert resolved is not None
    assert resolved.document["metadata"]["name"] == name


def test_refs() -> None:
    assert parse_ref("org://acme-baseline@^2").range is not None
    assert parse_ref("./team.yaml").scheme == "file"
    with pytest.raises(SpecError, match="extends"):
        parse_ref("org://acme@^^2")
