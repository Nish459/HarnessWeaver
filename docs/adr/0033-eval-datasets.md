# ADR-0033: Eval datasets and graders

**Status:** Accepted

## Decision

Eval datasets are YAML with `suite`, `task`, suite and case `graders`, `thresholds` and `cases`; graders are `Evaluator` providers built from `{name: settings}`, where a single setting fills the config's `SHORTHAND` field, and are labelled `name`, `name:value` or `name#n`. Deterministic graders score 0 or 1 and read non-text outputs as canonical JSON. `status` joins the guide's graders.

## Why

One format for CI and production; labels make baselines and reports stable without ids on every grader; a port lets promptfoo, DeepEval or Ragas plug in; canonical text and number rules let Python and TypeScript grade identically (fixtures suite `evals`); red-team sets need to assert that a run was blocked.
