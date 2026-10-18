"""The pytest plugin: ``pytest --harnessweaver-conformance=<namespace>`` (RULES T5).

Registered through the ``pytest11`` entry point, so it is available wherever
harnessweaver is installed. Without the option it does nothing.

The option takes an installed plugin's namespace, ``harnessweaver`` for the
built-in plugin, or ``module:attribute`` for an in-repo plugin, and may be given
more than once. The checks are in :mod:`harnessweaver.testing.conformance`.
"""

from pathlib import Path

import pytest

OPTION = "--harnessweaver-conformance"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("harnessweaver")
    group.addoption(
        OPTION,
        action="append",
        default=[],
        metavar="NAMESPACE",
        help="run the HarnessWeaver conformance suite on a plugin (namespace or module:attribute)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "harnessweaver_conformance: a HarnessWeaver conformance check"
    )
    suite = Path(__file__).with_name("conformance_suite.py")
    named = any(Path(arg.split("::")[0]).resolve() == suite for arg in config.args)
    if config.getoption(OPTION) and not named:
        config.args.append(str(suite))
