# ADR-0021: How approved steps resume

**Status:** Accepted. Amended by [ADR-0045](0045-what-an-approval-covers.md), which limits how long a match lasts.

## Decision

An approved step resumes from its checkpoint in `direct`, and by running the interrupted handler or workflow step again in `session` and `workflow`. Approvals are matched by tool name and arguments, or by the output's content, so the repeated call doesn't ask twice.

## Why

App code can't be resumed in the middle of a function. Running the step again, as LangGraph's interrupts do, keeps handlers plain async functions.
