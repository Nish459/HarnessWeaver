## What and why

<!-- What does this change do, and why? Cite rules (R*, C*, S*...) or ADRs where relevant. -->

## Review checklist ([RULES.md](../RULES.md#review-checklist))

- [ ] No invariant (R1-R14) is weakened; any rule exception has an ADR.
- [ ] Contract changes start in the models, schemas and fixtures, and pass in Python and TypeScript (R11, T4).
- [ ] New middleware declares `fail_mode`; baseline middleware is `closed` (R2).
- [ ] New guards ship with `mode: log_only` (R8).
- [ ] Nothing raw reaches logs or spans before redaction (R9).
- [ ] No new core dependency (R6); any new dependency has an ADR (C10).
- [ ] Tests are offline, cover the change, and include property tests or fixtures where relevant (T1-T4).
- [ ] Docs and `CHANGELOG.md` are updated (D1), using only keyboard characters (D5).
- [ ] `make check` is green (G5); the commit is approved by a human (G1).
