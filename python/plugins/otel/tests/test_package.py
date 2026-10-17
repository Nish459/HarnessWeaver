from importlib.metadata import version

import harnessweaver_otel


def test_version_matches_distribution_metadata() -> None:
    assert harnessweaver_otel.__version__ == version("harnessweaver-otel")
