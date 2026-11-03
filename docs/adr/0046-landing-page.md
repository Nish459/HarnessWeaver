# ADR-0046: The website: a landing page at the root, the docs under /docs/

**Status:** Accepted. Amended by [ADR-0047](0047-docs-for-users.md).

## Decision

The website has a landing page at `/` and the docs under `/docs/`. The landing page is plain HTML and CSS in `website/` (`index.html`, `404.html` and `site.css`), with no build step and no framework, and it reuses the docs' logo, favicon, colors and font. `mkdocs.yml` builds the docs into `site/docs/` (`site_dir`), and an `on_post_build` hook in `scripts/docs_hooks.py` then copies `website/` to `site/`, so `mkdocs build --strict`, and with it `make docs` and the Vercel build, writes the whole website to `site/`. `mkdocs serve` builds into a temporary folder and serves the docs alone, so the hook copies nothing then.

The docs header's logo leads to the landing page (`extra.homepage: ../`). `vercel.json` sets `trailingSlash: true`, so `/docs` redirects to `/docs/`: the docs' links are relative, and without the slash a browser would resolve them against the site's root. Vercel serves `site/404.html` for every missing path, under `/docs/` too, so that page links from the site's root. `make site-serve` previews `site/` the same way, since Python's `http.server` answers a missing path with its own error page. A test checks that the landing page's links into the docs name pages that exist, since the strict build doesn't read `website/`.

## Why

A landing page introduces the framework to a reader who hasn't yet decided to read the docs; the docs' home page (ADR-0042) is for one who has. Plain HTML adds no dependency (C10) and needs no toolchain to edit. A Material template override would tie the page's layout to the theme's internals, which MkDocs 2.0 is expected to break (ADR-0041). Building the landing page from `mkdocs build` keeps one command for CI, Vercel and contributors, and keeps `vercel.json`'s build command unchanged.
