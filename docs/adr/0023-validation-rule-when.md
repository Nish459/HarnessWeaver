# ADR-0023: A validation rule's when describes a violation

**Status:** Accepted

## Decision

A `validation.rules[].when` expression describes a violation (true means the output breaks the rule), like `policy.rules[].when`; an expression that can't be evaluated counts as broken.

## Why

One reading of `when` across the spec; failing closed on a rule that can't be checked.
