from importlib.metadata import version

import harnessweaver_monty


def test_version_matches_distribution_metadata() -> None:
    assert harnessweaver_monty.__version__ == version("harnessweaver-monty")
