# ADR-0030: Context governance runs before context.after

**Status:** Accepted

## Decision

Context governance (ACL re-check, labels, caps) runs inside the governed context call, before the `context.after` middleware, for fetched and app-supplied items alike; every drop is traced by item id.

## Why

Defense in depth against a misbehaving provider can't depend on middleware order, and the same rules must cover items the app retrieved itself.
