# ADR-0025: Where the governor runs, and one way to combine policy rules

**Status:** Accepted

## Decision

The governor's steps 1 to 7 run inside the governed tool call after the `tool.before` middleware, on the final arguments, and step 9 before the `tool.after` middleware; every decision is a `harness.governor` trace note. Every `PolicyEngine` combines `policy.rules` the same way: among rules whose `when` is true `deny` beats `require_approval` beats `allow`, the first of equals decides, a `when` that can't be evaluated never loosens (deny and approval rules count as matching, allow rules don't), and `default_effect` applies when none match. Rules carry a `hook` (`tool.before`, default, or `run.start`); `run.start` rules only restrict.

## Why

Middleware may rewrite arguments, so checks that run first could be bypassed; one combination rule keeps `cel_lite`, `cel.policy` and future engines interchangeable and testable from one fixture suite; failing closed without letting an unevaluable allow grant anything (R3).
