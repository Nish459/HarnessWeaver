# ADR-0020: Halting outcomes raise RunInterrupted errors

**Status:** Accepted

## Decision

A hook that halts a run raises a taxonomy error: `RunBlocked`, `RunEscalated` or `RunSuspended`, all `RunInterrupted` (codes `blocked`, `escalated`, `suspended`). In run style the harness turns it into the run's status; in session style the app's code sees it. `NotFound` (code `not_found`) covers unknown tasks, runs and approvals.

## Why

One mechanism stops every integration style, apps can catch one base class, and only taxonomy errors cross a public boundary (C5).
