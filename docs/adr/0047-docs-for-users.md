# ADR-0047: The docs site leaves out the ADRs and outside inspirations

**Status:** Accepted. Amends [ADR-0042](0042-docs-structure.md) and [ADR-0046](0046-landing-page.md).

## Decision

- The ADRs stay in `docs/adr/`, indexed by DESIGNS.md No. 28, but the docs site leaves them out (`exclude_docs` in `mkdocs.yml`). Site pages explain behavior in their own words and don't link to ADRs.
- The docs, the landing page and the READMEs don't name another product as a model or an inspiration for HarnessWeaver or its docs. Instead they need to clearly and correctly explain about it.
- Alternatives and competitors are named clearly, on the Alternatives and comparisons page (`docs/about/alternatives.md`), with how HarnessWeaver differs from each.
- Elsewhere, the docs name a product only where HarnessWeaver works with it: a plugin, an adapter, a generated config, something the reader installs or configures, or an integration marked *planned*.

## Why

ADRs tell contributors why the project decided something. A reader of the docs needs what the framework does and how to use it, and 46 decision records in the navigation sat between them and that. Saying that HarnessWeaver or its docs follow another product tells a reader nothing they can use, so the docs explain HarnessWeaver directly. A reader choosing a tool does need the alternatives, named and compared accurately in one place.
