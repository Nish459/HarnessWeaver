# ADR-0013: Versioned prompts without a template language

**Status:** Accepted

## Decision

Prompts are resolved by `name@version` from files and rendered with `str.format_map`. There is no template language.

## Why

The guide's API needs versioned prompts, but templating is a non-goal (R12). Bring Jinja, BAML or POML through a plugin if needed.
