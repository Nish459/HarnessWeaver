"""Run each tutorial chapter the way a reader would: from its own folder, offline.

Every folder in ``docs_src/tutorial/`` is the reader's project as it stands at the end
of one chapter, and each has its own copy of the ``helpdesk`` package. ``docs_src/home/``
is the example on the home page, set up the same way. The ``chapter``
fixture copies a folder to a temporary directory (so runs that write state or
baselines never touch the repository), makes it the working directory, puts it first
on ``sys.path`` and forgets any ``helpdesk`` modules another chapter imported, so the
spec's import paths resolve to this chapter's code.
"""

import importlib.util
import shutil
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest

DOCS_SRC = Path(__file__).resolve().parents[1]
TUTORIAL = DOCS_SRC / "tutorial"
PACKAGE = "helpdesk"


def _forget_package() -> None:
    """Drop every ``helpdesk`` module, so the next import reads the current chapter."""
    for name in [n for n in sys.modules if n == PACKAGE or n.startswith(PACKAGE + ".")]:
        del sys.modules[name]


class Chapter:
    """One tutorial chapter, copied to a temporary working directory."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def script(self, name: str) -> ModuleType:
        """Import one of the chapter's scripts (``main.py``) as a fresh module.

        Raises:
            FileNotFoundError: When the chapter has no such script.
        """
        path = self.folder / name
        spec = importlib.util.spec_from_file_location(f"tutorial_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


@pytest.fixture
def chapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], Chapter]]:
    """Return a function that sets up the named chapter and returns it."""

    def setup(name: str) -> Chapter:
        folder = tmp_path / name
        source = TUTORIAL / name if (TUTORIAL / name).is_dir() else DOCS_SRC / name
        shutil.copytree(source, folder, ignore=shutil.ignore_patterns("__pycache__"))
        monkeypatch.chdir(folder)
        monkeypatch.setenv("HARNESSWEAVER_ENV", "offline")
        monkeypatch.syspath_prepend(str(folder))
        _forget_package()
        return Chapter(folder)

    yield setup
    _forget_package()
