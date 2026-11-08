# harnessweaver-cel

A first-party [HarnessWeaver](https://github.com/Wise-DreamerZ/HarnessWeaver) plugin for CEL policies. It contributes `cel.policy`, a `PolicyEngine` that evaluates `policy.rules` in full [CEL](https://cel.dev) through cel-python.

It is built on the same plugin contract any third-party plugin uses: one `hw.Plugin` object, published through the `harnessweaver.plugins` entry point under the namespace `cel` (see DESIGNS.md No. 13).

```bash
uv add harnessweaver-cel        # or: uv add "harnessweaver[cel]"
```

```yaml
policy:
  use: cel.policy
  default_effect: allow
  rules:
    - { id: big-refunds, when: "args.amount_usd > 100", effect: require_approval }
    - { id: contractors, when: "principal.roles.exists(r, r == 'contractor')", effect: deny }
```

Rules combine exactly as they do in the built-in `cel_lite` engine (ADR-0025), and both pass the shared `governor` fixtures. Full CEL is stricter than cel-lite: it doesn't mix ints and doubles (`1 + 0.5` is an error), and an error in a rule counts as unevaluable, so `deny` and `require_approval` rules still apply. The tests list every `expr` fixture where cel-python 0.5 and cel-lite differ, and why.

Rules are compiled when the harness loads, so invalid CEL fails then. Importing the plugin imports nothing from cel-python (S8).

## Conformance

From this package's directory (at the repository root, `make conformance` checks every first-party plugin):

```bash
uv run pytest --harnessweaver-conformance=cel
```
