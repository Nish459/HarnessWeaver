# ADR-0018: Locks forbid changes, not restatements; bounds accumulate

**Status:** Accepted

## Decision

A lock forbids *changing* a value (or anything under it), not restating it. Bounds from several profiles accumulate and are never loosened by a later layer.

## Why

Apps can repeat baseline values for readability without failing; stacking org profiles can only tighten.
