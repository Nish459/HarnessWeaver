# ADR-0028: Tools given in code carry manifests; stale pins block calls

**Status:** Accepted

## Decision

Tools given in code carry a manifest (`ToolDescription.from_manifest`), so `tools.require_manifest` covers them. A pinned digest that doesn't match blocks the tool's calls rather than failing the load; `doctor` fails it and warns about unpinned manifests with the digest to pin.

## Why

One rule for every tool (S2); a stale pin is a security finding about one tool, not a reason to take the whole app down, and `doctor` makes it visible.
