# ADR-0004: cel-lite, the built-in expression language

**Status:** Accepted

## Decision

Built-in **cel-lite** expression language (a CEL subset) for policy, rules, approvals and business rules; full CEL as the `cel.policy` provider in `harnessweaver-cel`. It covers literals, field/index access, `has()`, arithmetic, comparison, `in`, `&&`/`||` with CEL's error absorption, `?:`, `size`, `int`, `double`, `string`, `startsWith`, `endsWith`, `contains`, `matches`, and the `exists`, `all`, `exists_one`, `map`, `filter` macros. Unknown functions and (when declared) unknown variables fail at compile time. Three deliberate differences from CEL keep Python and TypeScript identical: mixed int/double arithmetic gives a double instead of an error; integral floats in *data* are treated as ints (JSON numbers have no int/double distinction in JavaScript); `string(double)` prints like JavaScript's `Number#toString`.

## Why

`cel-python` pulls in `google-re2` and `pendulum`. A CEL-compatible subset keeps rules portable to TS and real CEL engines, sharing fixtures (suite `expr`).
