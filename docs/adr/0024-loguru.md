# ADR-0024: Logging through loguru

**Status:** Accepted

## Decision

Logging goes through **loguru** in the core and the first-party plugins, and it becomes the core's fifth dependency (amends ADR-0003, R6 and C6). Each package that logs calls `logger.disable(__name__)` when it is imported, so it is silent until the app calls `logger.enable(...)`; library code never adds sinks. Messages carry ids and error types, never content (R9).

## Why

One logging API that is simpler to use and to configure than `logging.getLogger` per area. Disabling by default follows loguru's own advice for libraries, so an app's log output is its own decision. loguru is pure Python with no dependencies outside Windows, so the core stays small.
