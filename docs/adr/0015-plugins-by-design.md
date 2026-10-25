# ADR-0015: Plugins are defined by design, not by name

**Status:** Accepted

## Decision

**Plugins are defined by design, not by name.** One contract (`hw.Plugin` exposed through the `harnessweaver.plugins` entry-point group, or `plugins.local` for in-repo code) for first-party, third-party and built-in contributions. Names are namespaced by the plugin; plugins are imported only when the spec references them; orgs can lock an allow-list.

## Why

Anyone can build a plugin in their own repo and use it with no change to HarnessWeaver; one entry point per distribution keeps discovery cheap and lazy; namespaces make ownership unambiguous; allow-lists keep the supply chain governable.
