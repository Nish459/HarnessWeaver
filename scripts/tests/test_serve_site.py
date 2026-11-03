"""Tests for scripts/serve_site.py: the preview answers a missing path with the site's 404 page."""

import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from serve_site import SiteHandler


@pytest.fixture
def site(tmp_path: Path) -> Iterator[str]:
    """A preview of a small built site, served on a free local port; yields its address."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "index.html").write_text("landing")
    (tmp_path / "docs" / "index.html").write_text("docs")
    (tmp_path / "404.html").write_text("not found page")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SiteHandler, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("path", ["/nope", "/docs/nope/"])
def test_a_missing_path_gets_the_sites_404_page(site: str, path: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(site + path)
    with caught.value as error:
        assert error.code == 404
        assert error.read() == b"not found page"


@pytest.mark.parametrize(("path", "body"), [("/", b"landing"), ("/docs", b"docs")])
def test_pages_that_exist_are_served(site: str, path: str, body: bytes) -> None:
    # /docs redirects to /docs/, as on Vercel, and urllib follows the redirect.
    with urllib.request.urlopen(site + path) as response:
        assert response.read() == body
