# Recipes

Short recipes for specific jobs. Each assumes you know the [Tutorial](../tutorial/index.md).

| Recipe | For |
| --- | --- |
| [Govern an existing client](wrap-a-client.md) | An app that already calls OpenAI or Anthropic: trace, cost, budget and guard every call in three lines |
| [Write an org baseline](org-baseline.md) | Platform and security teams: the profile every app extends, its locks, bounds, versions and tests |
| [Troubleshooting](troubleshooting.md) | A spec that doesn't load, a run that's blocked: every error and code, with what to do |

More recipes live with the topic they belong to:

- Promote a guard from shadow mode: [Guardrails](../tutorial/guardrails.md#shadow-mode) and [Evals](../tutorial/evals.md#the-shadow-guard-report).
- Approve a run after a restart: [State and replay](../tutorial/state.md#approve-after-a-restart).
- Check a spec change against real production runs: [State and replay](../tutorial/state.md#replay-a-run).
- Record a real model once and replay it in tests: [Testing](../tutorial/testing.md#recording-a-real-model-once).
- Run a guard that exists only in Python from another language: [harnessd](../advanced/sidecar.md#guards-that-run-in-the-sidecar).
