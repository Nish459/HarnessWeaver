from pathlib import Path

import harnessweaver as hw
from harnessweaver.contracts import (
    API_VERSION,
    CONTRACTS,
    json_schemas,
    stale_schemas,
    write_schemas,
)


def _schemas_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "contracts" / "schemas").is_dir():
            return parent / "contracts" / "schemas"
    raise RuntimeError("contracts/schemas not found")


def test_checked_in_schemas_match_the_models() -> None:
    # RULES R11 / ADR-0005: regenerate with `make schemas` after changing a contract.
    assert stale_schemas(_schemas_dir()) == []


def test_every_schema_is_draft_2020_12_with_an_id() -> None:
    for name, schema in json_schemas().items():
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == f"urn:harnessweaver:v1:{name}"
        assert schema["title"]


def test_write_schemas_replaces_stale_files(tmp_path: Path) -> None:
    (tmp_path / "removed-contract.schema.json").write_text("{}")
    write_schemas(tmp_path)
    assert {p.name.removesuffix(".schema.json") for p in tmp_path.iterdir()} == set(CONTRACTS)
    assert stale_schemas(tmp_path) == []
    (tmp_path / "outcome.schema.json").write_text("{}")
    assert stale_schemas(tmp_path) == ["outcome.schema.json is out of date"]


def test_api_version_is_exported() -> None:
    assert hw.API_VERSION == API_VERSION == "harnessweaver/v1"


def test_main_writes_then_checks(tmp_path: Path, capsys: object) -> None:
    from harnessweaver.contracts import main

    assert main([str(tmp_path)]) == 0
    assert main(["--check", str(tmp_path)]) == 0
    (tmp_path / "decision.schema.json").unlink()
    assert main(["--check", str(tmp_path)]) == 1
    assert "decision.schema.json is missing" in capsys.readouterr().out  # type: ignore[attr-defined]
