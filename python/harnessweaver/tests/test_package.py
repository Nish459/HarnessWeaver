import re
from importlib.metadata import requires, version

import harnessweaver

# RULES R6: the core depends on exactly these packages. Anything else
# belongs in a plugin, the CLI or the sidecar.
ALLOWED_CORE_DEPENDENCIES = {"pydantic", "opentelemetry-api", "pyyaml", "anyio"}


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_version_matches_distribution_metadata() -> None:
    assert harnessweaver.__version__ == version("harnessweaver")


def _requirement_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9._-]+", requirement)
    assert match is not None
    return _normalize(match.group(0))


def test_core_runtime_dependencies_are_only_the_allowed_four() -> None:
    runtime = [r for r in requires("harnessweaver") or [] if "extra ==" not in r]
    assert {_requirement_name(r) for r in runtime} == ALLOWED_CORE_DEPENDENCIES
