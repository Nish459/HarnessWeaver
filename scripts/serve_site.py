"""Serve the built website in ``site/`` the way Vercel does (ADR-0046): ``make site-serve``.

``python -m http.server`` answers a missing path with an error page of its own. Vercel
answers it with the site's ``404.html``, under ``/docs/`` too, and so does this preview.
Like Vercel, it redirects a folder's address without its trailing slash (``/docs``) to
the address with it, so the docs' relative links resolve.
"""

import contextlib
import sys
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE = Path(__file__).parents[1] / "site"


class SiteHandler(SimpleHTTPRequestHandler):
    """Serves the files in its ``directory``, and its ``404.html`` for a path with no file."""

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Answer a 404 with the site's ``404.html``, and any other error as http.server does."""
        page = Path(self.directory) / "404.html"
        if code != HTTPStatus.NOT_FOUND or not page.is_file():
            super().send_error(code, message, explain)
            return
        body = page.read_bytes()
        self.send_response(code, message)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def main(argv: list[str]) -> int:
    """Serve ``site/`` on 127.0.0.1 at the port in ``argv`` (8000 by default) until stopped."""
    if not (SITE / "index.html").is_file():
        print("site/ has no website yet: run `make docs` first", file=sys.stderr)
        return 1
    port = int(argv[0]) if argv else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(SiteHandler, directory=str(SITE)))
    print(f"Serving the website at http://127.0.0.1:{port}/ (Ctrl+C stops it)")
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
