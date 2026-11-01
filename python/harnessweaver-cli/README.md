# harnessweaver-cli

Developer tooling for [HarnessWeaver](../../README.md). Installs the `harnessweaver` command. The full reference, with every option and exit code, is [docs/cli.md](../../docs/cli.md).

```bash
uv add --dev harnessweaver-cli
harnessweaver --help
```

## Start a project

```bash
harnessweaver init invoice-bot              # the extraction template; -t picks another
cd invoice-bot
harnessweaver spec validate --env offline   # load it the way the app will
harnessweaver test                          # its tests, offline
```

`init` copies a template and puts the project name in it; there is no template
language. A plugin's templates are named `<namespace>.<template>`
(`harnessweaver init -t acme.rag`). Every template's output passes its own tests
(RULES T6).

| Template | What you get |
| --- | --- |
| `extraction` (default) | Typed extraction with schema validation, one repair, PII and secrets guards, a golden set |
| `rag` | A session flow that routes the question, retrieves ACL-checked passages and answers with citations the output guard checks |
| `agent` | A Pydantic AI agent with two governed tools, one of them approval-gated, a policy rule and a red-team eval set |
| `workflow` | A three-stage step graph: a parallel stage, then a reply in an evaluator-optimizer loop |
| `chat` | A chat turn with memory, a topic guard and a streamed answer moderated chunk by chunk |

## Commands

| Command | What it does |
| --- | --- |
| `init [DIR] [-t TEMPLATE] [--name NAME] [--force]` | Start a project: `harness.yaml`, an offline overlay, code, a prompt, evals and tests. Never overwrites without `--force` |
| `spec validate [SPEC] [-e ENV] [--format text\|json]` | Load the spec with every check the app runs: layers, locks, bounds, plugins, tasks, reachable hooks (R4). Prints the adoption level |
| `spec explain [SPEC] [--path PREFIX]` | Every effective value, the layer it came from, and its locks and bounds |
| `spec diff BEFORE AFTER [--exit-code]` | Compare two effective specs as Markdown, for PR comments. Either side can be `git:<ref>:<path>`, read with the profiles committed at that ref |
| `doctor [SPEC] [--strict]` | Adoption level and what the next level needs, hooks each task's runner reaches, duplicate retry owners (R5), unpinned profiles, shadow guards (R8), content capture (R9), plugin installation problems. Exits 1 on a failure, or on a warning with `--strict` |
| `hooks [SPEC] [--task TASK]` | The middleware on every hook point in the order it runs, with band, fail mode and timeout |
| `test [-e ENV] [PYTEST ARGS...]` | Run the app's tests with `HARNESSWEAVER_TEST_MODE=1` and the `offline` overlay |
| `contracts export [DIR] [--check]` | Write the JSON Schema of every contract, or report drift |
| `eval run [SPEC] [--suite NAME] [--task TASK] [--update-baseline]` | Run the spec's eval suites, compare with `.harness/baselines`, print the shadow-guard report. Exits 1 on a missed threshold or a regression, 2 when the suites can't run |
| `eval report [SPEC] [--task TASK]` | The production runs online evals sampled and graded |
| `policy test [SPEC] [--cases FILE]` | Check a table of tool calls (`policy_tests.yaml`) against the governor's verdicts, as a dry run |
| `replay RUN_ID [SPEC]` | Run a recorded run again against the current code and spec, and show what changed |
| `add guard USE [SPEC] [--stage S] [--id ID] [--action A] [--set KEY=VALUE]` | Add a guard in shadow mode (`mode: log_only`, R8). Comments in `harness.yaml` are kept; an edit that doesn't load is taken back |
| `add tool MODULE:FUNCTION [SPEC] [--dir tools] [--risk R] [--side-effect S]` | Write a tool manifest from the function's signature and docstring, and add its directory to `tools.manifests` |
| `tools pin [SPEC] [--tool NAME]` | Write each manifest's `definition_digest`, so a tool that changes unreviewed is blocked (S2) |
| `plugin new NAMESPACE [DIR]` | Scaffold a standalone plugin package with a sample guard and tests that run the conformance suite |
| `plugin list [--format text\|json]` | Installed plugins: namespace, distribution, version, contract range, compatibility |
| `sidecar [SPEC] [-e ENV] [--host H] [--port P] [--token-env VAR]` | Serve the spec to other languages: runs `harnessd` (needs `harnessweaver-sidecar` and a token, S6) |
| `gateway litellm [SPEC] [-o FILE]` | A LiteLLM Proxy config from the spec: gateway models and aliases, retries, a timeout, no message logging, and a tool-permission guardrail from the manifests |
| `gateway mcp [SPEC] [-o FILE]` | A neutral tool allow-list for an MCP gateway: each allowed tool's server, digest and scopes, and the withheld tools with the reason |
| `dev [SPEC] [-e ENV] [--up]` | Write `.harness/dev/`: LiteLLM, an OTel collector, Langfuse and harnessd in a Compose file, wired to the spec, with local secrets in `.env`. `--up` starts it |

Every command that takes `SPEC` defaults to `harness.yaml`, takes
`--profile-dir` to find `org://` profiles, and makes the spec's directory
importable, as it is when the app runs from there.
