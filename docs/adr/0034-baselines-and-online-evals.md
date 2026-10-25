# ADR-0034: Eval baselines, exit codes and online sampling

**Status:** Accepted

## Decision

Baselines live in `.harness/baselines/<task>.<suite>.json`; a regression is a case that passed in the baseline and fails now; `eval run` exits 1 for a missed threshold or a regression and 2 when it can't run. Online sampling picks runs by FNV-1a of the run id, grades them only with deterministic graders in a platform-band `run.end` middleware that fails open, and keeps `OnlineSample`s (no content) through new `StateStore` methods. A shadow guard's false positives are cases without a `guard_fired` grader naming it.

## Why

Per-task file names avoid two tasks' `golden` suites colliding; CI must tell a quality drop from a broken setup; a hash of the id samples the same runs everywhere; judges' cost and latency don't belong in production runs, and sampling must never fail a run (R2 is for controls); eval cases are the ground truth for promoting a guard (R8).
