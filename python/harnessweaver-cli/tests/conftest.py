import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from harnessweaver_cli.scaffold import render_template


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """The extraction template rendered as ``demo``, as the working directory.

    Loading a spec makes its directory importable (as ``app``), so the import
    path and the ``app`` modules are put back afterwards.
    """
    root = tmp_path / "demo"
    render_template("extraction", root, "demo")
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield root
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
