# CLAUDE.md

@AGENTS.md
@RULES.md

## Claude Code notes

These add to AGENTS.md and RULES.md (imported above). They don't replace them.

### How to work on a change
1. Read the DESIGNS.md sections the change touches. Don't re-derive designs that are already decided there. If a design must change, propose an ADR.
2. Always load the `ponytail` skill before implementing anything, and follow it.
3. Write failing tests first (including contract fixtures when behavior is part of a contract), then implement.
4. While implementing, give every module, package, class, method and function a docstring wherever possible. Comment complex or long logic enough to explain how it works and why (see the conventions in AGENTS.md).
5. Run `make check` (plus `pnpm -C typescript test` when TypeScript changed, and `make docs` when docs changed) until it's green.
6. Update the affected docs (the pages under `docs/`, and any README the change touches) and `CHANGELOG.md`.
7. Summarize what changed and anything not verified, then **ask for approval before committing** (G1). Never commit or push on your own initiative.

### Environment
- Use `uv run ...` and `uv add --package <member> ...`. Never `pip install`.
- Temporary files go in your scratchpad directory, not the repo.
- Tests must stay offline (R14). Never put real API keys in fixtures, cassettes or examples (S7).
- Write only keyboard characters (D5), including in commit messages: `No. 13`, not a section sign; `-`, `->` and `...` instead of dashes, arrows and ellipses.

### External APIs to verify, not recall
- **Anthropic plugin** (`harnessweaver-anthropic`): load the `claude-api` skill before writing or changing it, and use current model IDs from it.
- **Pydantic AI plugin** (`harnessweaver-pydantic-ai`): read the installed `pydantic_ai` source for `AbstractCapability`, hooks, `ApprovalRequired` and deferred tools.
- **pydantic-monty**, the **Vercel AI SDK** middleware API, **LiteLLM** config format and **OTel GenAI semconv** attribute names: check the installed package or current docs before coding against them.

### Keeping context lean
- Prefer reading the specific DESIGNS.md section you need over whole documents.
- The design guide in `docs/` is long. Search it for the topic you need rather than reading it end to end.
