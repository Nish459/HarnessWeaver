"""Tests for scripts/docs_hooks.py: the website is the landing page with the docs under /docs/."""

import re
from pathlib import Path

from docs_hooks import on_post_build

ROOT = Path(__file__).parents[2]
CONFIG_FILE = str(ROOT / "mkdocs.yml")


def test_a_docs_build_puts_the_landing_page_in_the_folder_above_it(tmp_path: Path) -> None:
    on_post_build({"site_dir": str(tmp_path / "site" / "docs"), "config_file_path": CONFIG_FILE})
    for name in ("index.html", "404.html", "site.css"):
        assert (tmp_path / "site" / name).read_bytes() == (ROOT / "website" / name).read_bytes()


def test_serving_the_docs_copies_nothing(tmp_path: Path) -> None:
    # `mkdocs serve` builds into a temporary folder of its own, such as mkdocs_1a2b3c.
    on_post_build({"site_dir": str(tmp_path / "mkdocs_1a2b3c"), "config_file_path": CONFIG_FILE})
    assert list(tmp_path.iterdir()) == []


def test_the_landing_page_links_only_to_docs_pages_and_files_that_exist() -> None:
    # The strict docs build doesn't check website/, so a renamed page would break a link here.
    links = re.findall(r'href="docs/([^"]*)"', (ROOT / "website" / "index.html").read_text())
    assert links
    for link in links:
        page = link.rstrip("/")
        if "." in Path(page).name:
            sources = [page]
        else:
            sources = [f"{page}.md", f"{page}/index.md"] if page else ["index.md"]
        assert any((ROOT / "docs" / source).is_file() for source in sources), link
