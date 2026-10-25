# ADR-0036: Governor dry runs and guard firing notes

**Status:** Accepted

## Decision

`ToolGovernor.authorize` takes `dry_run`, and `Harness.authorize` runs steps 1 to 7 on a call that never executes; `harnessweaver policy test` checks tables of calls with it. Guards that fire are traced as `harness.guard` notes (`guard_fired`, `guard_shadow`) naming the guard as `doctor` does.

## Why

Policy tests must exercise exactly the production decision, including manifests, approval rules and the trifecta, without using up rate limits; eval graders and reports need guard firings as data, not parsed from reasons.
