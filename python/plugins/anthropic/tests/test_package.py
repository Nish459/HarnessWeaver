from importlib.metadata import version

import harnessweaver_anthropic


def test_version_matches_distribution_metadata() -> None:
    assert harnessweaver_anthropic.__version__ == version("harnessweaver-anthropic")
