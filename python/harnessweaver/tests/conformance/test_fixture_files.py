import json
from pathlib import Path

# Every suite directory needs a runner here and in TypeScript (RULES R11). Add new
# suites to this set together with their test module.
SUITES_WITH_RUNNERS = {"durations", "expr", "hook_order", "outcomes", "semver"}


def test_every_suite_has_a_runner(fixtures_root: Path) -> None:
    suites = {path.name for path in fixtures_root.iterdir() if path.is_dir()}
    assert suites == SUITES_WITH_RUNNERS


def test_fixture_files_are_well_formed(fixtures_root: Path) -> None:
    for path in sorted(fixtures_root.glob("*/*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert set(document) == {"suite", "description", "cases"}, path
        assert document["suite"] == path.parent.name, path
        names = [case["name"] for case in document["cases"]]
        assert len(names) == len(set(names)), f"duplicate case names in {path}"
        assert all("expect" in case or "directions" in case for case in document["cases"]), path
