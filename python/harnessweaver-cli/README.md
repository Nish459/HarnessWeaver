# harnessweaver-cli

Developer tooling for [HarnessWeaver](../../README.md). Installs the `harnessweaver` command.

```bash
uv add --dev harnessweaver-cli
harnessweaver --help
```

## Start a project

```bash
harnessweaver init invoice-bot              # the extraction template
cd invoice-bot
harnessweaver spec validate --env offline   # load it the way the app will
harnessweaver test                          # its tests, offline
```

`init` copies a template and puts the project name in it; there is no template
language. A plugin's templates are named `<namespace>.<template>`
(`harnessweaver init -t acme.rag`). Every template's output passes its own tests
(RULES T6).

## Commands

| Command | What it does |
| --- | --- |
| `init [DIR] [-t TEMPLATE] [--name NAME] [--force]` | Start a project: `harness.yaml`, an offline overlay, code, a prompt, evals and tests. Never overwrites without `--force` |
| `spec validate [SPEC] [-e ENV] [--format text\|json]` | Load the spec with every check the app runs: layers, locks, bounds, plugins, tasks, reachable hooks (R4). Prints the adoption level |
| `spec explain [SPEC] [--path PREFIX]` | Every effective value, the layer it came from, and its locks and bounds |
| `spec diff BEFORE AFTER [--exit-code]` | Compare two effective specs as Markdown, for PR comments. Either side can be `git:<ref>:<path>` |
| `doctor [SPEC] [--strict]` | Adoption level and what the next level needs, hooks each task's runner reaches, duplicate retry owners (R5), unpinned profiles, shadow guards (R8), content capture (R9), plugin installation problems. Exits 1 on a failure, or on a warning with `--strict` |
| `hooks [SPEC] [--task TASK]` | The middleware on every hook point in the order it runs, with band, fail mode and timeout |
| `test [-e ENV] [PYTEST ARGS...]` | Run the app's tests with `HARNESSWEAVER_TEST_MODE=1` and the `offline` overlay |
| `contracts export [DIR] [--check]` | Write the JSON Schema of every contract, or report drift |

Every command that takes `SPEC` defaults to `harness.yaml`, takes
`--profile-dir` to find `org://` profiles, and makes the spec's directory
importable, as it is when the app runs from there.

*Planned:* `add`, `dev`, `eval`, `replay`, `plugin`, `gateway` and `sidecar`.
