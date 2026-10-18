from importlib.metadata import version

import harnessweaver_openai


def test_version_matches_distribution_metadata() -> None:
    assert harnessweaver_openai.__version__ == version("harnessweaver-openai")


def test_importing_the_plugin_imports_no_sdk() -> None:
    """Plugins are inert until used: the SDK loads on first use (RULES S8)."""
    import subprocess
    import sys

    code = "import sys, harnessweaver_openai; print('openai' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
