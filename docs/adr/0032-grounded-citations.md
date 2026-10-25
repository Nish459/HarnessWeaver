# ADR-0032: The grounded.citations guard

**Status:** Accepted

## Decision

`grounded.citations` checks that output sentences (ending at `.`, `!` or `?` and a space, or a line break) of at least `min_words` words cite a context id in square brackets; it proposes `repair` when fewer than `min_supported` do, or when a citation names an id the run didn't keep.

## Why

A cheap, deterministic grounding check that catches made-up sources; scoring how well a source supports a claim is left to later groundedness scorers and judges.
