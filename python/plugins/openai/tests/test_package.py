from importlib.metadata import version

import harnessweaver_openai


def test_version_matches_distribution_metadata() -> None:
    assert harnessweaver_openai.__version__ == version("harnessweaver-openai")
