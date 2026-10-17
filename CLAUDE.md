# CLAUDE.md

@AGENTS.md
@RULES.md

## Claude Code notes

These add to AGENTS.md and RULES.md (imported above). They don't replace them.

### How to work on a change
1. Read the DESIGNS.md sections the change touches. Don't re-derive designs that are already decided there. If a design must change, propose an ADR.
2. Write failing tests first (including contract fixtures when behavior is part of a contract), then implement.
3. Run `make check` (plus `pnpm -C typescript test` when TypeScript changed) until it's green.
4. Update the affected docs and `CHANGELOG.md`.
5. Summarize what changed and anything not verified, then **ask for approval before committing** (G1). Never commit or push on your own initiative.

### Environment
- Use `uv run …` and `uv add --package <member> …`. Never `pip install`.
- Temporary files go in your scratchpad directory, not the repo.
- Tests must stay offline (R14). Never put real API keys in fixtures, cassettes or examples (S7).

### External APIs to verify, not recall
- **Anthropic plugin** (`harnessweaver-anthropic`): load the `claude-api` skill before writing or changing it, and use current model IDs from it.
- **Pydantic AI plugin** (`harnessweaver-pydantic-ai`): read the installed `pydantic_ai` source for `AbstractCapability`, hooks, `ApprovalRequired` and deferred tools.
- **pydantic-monty**, the **Vercel AI SDK** middleware API, **LiteLLM** config format and **OTel GenAI semconv** attribute names: check the installed package or current docs before coding against them.

### Keeping context lean
- Prefer reading the specific DESIGNS.md section you need over whole documents.
- The design guide in `docs/` is long. Search it for the topic you need rather than reading it end to end.
