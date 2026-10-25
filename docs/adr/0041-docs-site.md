# ADR-0041: The docs site: MkDocs and Material

**Status:** Accepted

## Decision

The user documentation is a static site built with MkDocs and the Material theme (`mkdocs-material` 9.7, which requires `mkdocs` 1.6), from `docs/` and `mkdocs.yml`. Both live in a `docs` dependency group of the uv workspace, not in any package. `make docs` runs `mkdocs build --strict`, with link, anchor and navigation checks turned into errors, and CI runs it. Diagrams are Mermaid code blocks, rendered by Material through `pymdownx.superfences`. The root documents a reader meets on GitHub (`QUICKSTART.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`) are included in the site with `pymdownx.snippets`, so each has one source; they use absolute links so they work in both places. Each ADR has its own file under `docs/adr/`, and DESIGNS.md No. 28 indexes them. The design guide in `docs/` stays out of the site (it is linked on GitHub), because it may not be edited (D4). The Material team has announced that MkDocs 2.0 will break existing plugins and themes; Material 9.x pins `mkdocs<2`, so the site stays on MkDocs 1.6. If that becomes a problem, the migration to evaluate is Zensical, a static site generator from the creators of Material that documents compatibility with MkDocs projects.

## Why

The guide and the plan called for MkDocs with Mermaid. Material is the most used MkDocs theme, adds search, navigation and Mermaid rendering without plugins of our own, and needs nothing beyond Python, which every contributor already has. A dependency group keeps it out of every published package (R6, C10). A strict build means a renamed page or heading fails CI instead of leaving a broken link (D3). One source per document avoids two copies that drift apart.
