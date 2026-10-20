# __dist__

A HarnessWeaver plugin. It contributes everything under the namespace `__ns__`; the sample contribution is the guard `__ns__.banned_words`.

```bash
uv sync                  # install it, with pytest
uv run pytest            # its tests and the HarnessWeaver conformance suite
```

Use it from any app's `harness.yaml` once it is installed next to `harnessweaver`:

```yaml
guardrails:
  input:
    - { use: __ns__.banned_words, words: [lottery, wire transfer], mode: log_only }
```

New guards start in shadow mode (`mode: log_only`) and are promoted to `enforce` once evals back them. If the org baseline locks `plugins.allow`, ask the platform team to add `__ns__` to it.

## Add a contribution

1. Write it in `src/__ns___harness/` with its decorator: `@hw.provider(port=..., name="__ns__.<name>", ...)`, `@hw.middleware(...)`, `@hw.decider("<name>")`, `@hw.runner(...)` or `@hw.adapter(...)`. A contribution whose config has required fields declares `sample=` settings for the conformance suite.
2. List it in `plugin = hw.Plugin(...)` in `src/__ns___harness/__init__.py`.
3. Test it, and run `uv run pytest`: the conformance suite checks every contribution.

Build only against the public surface: `harnessweaver` (`hw.Plugin`, the decorators and the contract models), `harnessweaver.ports` and `harnessweaver.testing`. It is versioned with the contract (`contract=">=1.0,<2"`), so the plugin keeps working across HarnessWeaver releases within `harnessweaver/v1`.
