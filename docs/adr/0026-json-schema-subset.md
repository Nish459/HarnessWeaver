# ADR-0026: A JSON Schema subset validator in the core

**Status:** Accepted

## Decision

Tool arguments are checked by a small JSON Schema 2020-12 validator in the core: types, enum and const, object, array, string and number keywords, `allOf`/`anyOf`/`oneOf`/`not`, and `$ref` to `#/$defs`. Annotations are ignored; any other keyword fails the manifest at load. Problems name locations and rules, never values.

## Why

The core can't depend on `jsonschema` (R6), tool schemas need only this subset, TypeScript implements the same subset from the fixtures, and refusing unknown keywords means a schema never checks less than it says (R4, R9).
