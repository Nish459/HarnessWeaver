from importlib.metadata import version

import harnessweaver_pydantic_ai


def test_version_matches_distribution_metadata() -> None:
    assert harnessweaver_pydantic_ai.__version__ == version("harnessweaver-pydantic-ai")
