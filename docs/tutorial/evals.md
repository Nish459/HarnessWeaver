# Evals

Tests check that your controls work. **Evals** check that your tasks do their job: given these inputs, does triage pick the right category, and are red-team attempts stopped for the right reason? One dataset format serves CI and production. Suites run in CI against a stored **baseline**, so a change that breaks a passing case fails the build, and a sample of real production runs is graded as it ends.

## A golden set

Add `evals/golden.yaml`, a few cases the `triage` task must get right:

```yaml title="evals/golden.yaml"
--8<-- "docs_src/tutorial/evals/evals/golden.yaml"
```

- `graders` apply to every case. `schema_valid` checks the output matches `Triage`, and `{ field_equals: category }` compares that field with the case's `expect`.
- `thresholds.pass_rate` is the share of cases that must pass (1.0 by default).
- A case has an `id`, an `input`, what it `expect`s, and optionally its own `graders`, `principal` and `tenant`.

## A red-team set

A red-team suite holds cases that must be stopped, or must wait for a person. Add `evals/redteam.yaml` for the `orders` task:

```yaml title="evals/redteam.yaml"
--8<-- "docs_src/tutorial/evals/evals/redteam.yaml"
```

`status` checks how the run ended, and `guard_fired` checks which control fired, so a case can't pass by being stopped for the wrong reason. `guard_fired` counts a guard in shadow mode too, as "would have fired".

## Name the suites in the spec

```yaml title="harness.yaml (the evals section)"
--8<-- "docs_src/tutorial/evals/harness.yaml:111:114"
```

The offline model needs an answer for the crash case. A rule that matches its text does it:

```yaml title="harness.offline.yaml"
--8<-- "docs_src/tutorial/evals/harness.offline.yaml"
```

## Run them

```console
$ uv run harnessweaver eval run harness.yaml -e offline --update-baseline
ok: golden (triage): 2/2 passed, pass rate 1.0 (threshold 0.9)
  shadow guardrails.input[injection]: would fire on 0/2 (0.0); false positives: none; misses: none
  baseline written to .harness/baselines/triage.golden.json
ok: redteam (orders): 3/3 passed, pass rate 1.0 (threshold 1.0)
  shadow guardrails.input[injection]: would fire on 1/3 (0.333333); false positives: none; misses: none
  baseline written to .harness/baselines/orders.redteam.json
```

`eval run` runs every case through its task, with the runs kept in memory, grades them, and compares each suite with its baseline. `--update-baseline` saves the results. Commit `.harness/baselines/`, and from then on a case that passed in the baseline and fails now is a **regression**:

| Exit code | Means |
| --- | --- |
| 0 | Every suite met its threshold, with no regression |
| 1 | A suite missed its threshold, or a case regressed |
| 2 | The suites couldn't run: a broken spec, a missing dataset |

Run `eval run` in CI, next to `policy test`. In code, `await harness.evaluate("evals/golden.yaml")` returns a `SuiteResult`.

## The shadow-guard report

For each guard in shadow mode, `eval run` reports how many runs it would have fired on, its **false positives** (cases where it would fire but that don't expect it) and its **misses** (cases that expect it where it wouldn't fire). Above, the injection guard would have fired on the injected request, the one case that expects it, and on nothing else.

That is the evidence for promoting it. The one-line, reviewed change is `mode: log_only` to `mode: enforce` (RULES R8).

## Graders

| Grader | Passes when |
| --- | --- |
| `exact` | The output equals `expect` |
| `field_equals` | A field of the output (a dotted path) equals the same field of `expect` |
| `numeric_close` | A number is within `tolerance` of `expect`'s |
| `contains`, `regex` | The output's text contains every listed text, or matches a pattern |
| `citation_present` | The output cites the listed ids, like `[help-refunds]` |
| `schema_valid` | The run completed and its output matches the task's output type |
| `guard_fired` | The listed guards fired (or would have, in shadow mode). `fired: false` for cases that must stay quiet |
| `status` | The run ended with one of the listed statuses |
| `llm_judge` | A model scores the output against a `rubric`, at or above `threshold` |

All but `llm_judge` are deterministic. [Providers](../reference/providers.md#graders) has every grader's settings and how results label them.

## Online sampling

`evals.online` grades a sample of **production** runs as they end. A run is picked by a hash of its id, so every process and language agrees on which runs are sampled. Online graders must be deterministic and can't use `expect`. The samples are kept in the state store, without any content, and summarized by:

```console
$ uv run harnessweaver eval report harness.yaml --task orders
```

It reports run statuses, grader pass rates, and how often each shadow guard would have fired on real traffic. Use a durable state store, so samples accumulate.

## Recap

- Eval datasets list cases and graders. `harnessweaver eval run` grades them and compares with committed **baselines**, so a regression fails CI.
- Red-team suites check that attacks are stopped, and by the right control.
- The shadow-guard report is the evidence for promoting a guard, and `evals.online` grades a sample of production runs.
