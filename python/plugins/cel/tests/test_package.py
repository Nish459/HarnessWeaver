from importlib.metadata import version

import harnessweaver_cel


def test_version_matches_distribution_metadata() -> None:
    assert harnessweaver_cel.__version__ == version("harnessweaver-cel")
