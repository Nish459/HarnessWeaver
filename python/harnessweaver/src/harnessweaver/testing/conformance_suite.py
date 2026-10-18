"""The conformance suite, collected by ``pytest --harnessweaver-conformance=<namespace>``.

Every check in :mod:`harnessweaver.testing.conformance` runs once for each
contribution it applies to, with ids like ``results[pii.regex]``.
"""

from typing import Any

import pytest

from harnessweaver.core.registry import LoadedPlugin
from harnessweaver.testing import conformance
from harnessweaver.testing.pytest_plugin import OPTION

pytestmark = pytest.mark.harnessweaver_conformance


def _plugins(config: pytest.Config) -> list[LoadedPlugin]:
    selectors: list[str] = []
    for value in config.getoption(OPTION) or []:
        selectors.extend(part.strip() for part in value.split(",") if part.strip())
    return [conformance.load_plugin(selector) for selector in selectors]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    plugins = _plugins(metafunc.config)
    if "conformance_plugin" in metafunc.fixturenames:
        metafunc.parametrize(
            "conformance_plugin", plugins, ids=[p.plugin.namespace for p in plugins]
        )
    if "conformance_case" in metafunc.fixturenames:
        cases = [
            (check, function, subject)
            for loaded in plugins
            for subject in conformance.subjects(loaded)
            for check, function in conformance.CHECKS
            if conformance.applies(check, subject)
        ]
        metafunc.parametrize(
            "conformance_case",
            cases,
            ids=[f"{check}[{subject.name}]" for check, _, subject in cases],
        )


def test_plugin(conformance_plugin: LoadedPlugin) -> None:
    conformance.check_plugin(conformance_plugin)


def test_import_is_inert(conformance_plugin: LoadedPlugin) -> None:
    conformance.check_import_is_inert(conformance_plugin.source.module)


@pytest.mark.anyio
async def test_contribution(conformance_case: tuple[str, Any, conformance.Subject]) -> None:
    check, function, subject = conformance_case
    if check == "builds":
        function(subject)
    else:
        await function(subject)
