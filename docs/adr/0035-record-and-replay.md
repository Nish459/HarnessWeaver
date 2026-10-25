# ADR-0035: Recording and replaying runs

**Status:** Accepted

## Decision

`state.record: true` keeps each run's model answers, tool results and approvals as `RecordedCall`s through new `StateStore` methods. `Harness.replay` and `harnessweaver replay` run the task again on a copy of the harness built from the current spec, answering from the recording, never executing tools, answering repeated approvals from the recorded ones, with the copy's runs in memory; the report compares statuses, outputs and trace decisions.

## Why

The guide's replay of production runs against current code and spec needs the run's inputs from outside, and a replay must never repeat a side effect or spend tokens. Recordings hold content, so they are opt-in, kept only in the app's own store, and lockable by the org (R9).
