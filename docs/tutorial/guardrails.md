# Guardrails

Customers put e-mail addresses in their messages, and models occasionally echo secrets. **Guards** check content at fixed points in a run and redact it, block it, or record what they would have done. This chapter redacts personal data before the model sees it, blocks secrets in the output, and adds a prompt-injection check in shadow mode.

## Add guards

Add a `guardrails` section to `harness.yaml`:

```yaml title="harness.yaml (the end of the file)"
--8<-- "docs_src/tutorial/guardrails/harness.yaml:44:55"
```

??? example "The whole harness.yaml"
    ```yaml
    --8<-- "docs_src/tutorial/guardrails/harness.yaml"
    ```

Each guard has an `id` (its name in traces), a provider in `use`, and the provider's own settings. `action` replaces what the provider proposes when it finds something, and `mode: log_only` puts the guard in **shadow mode**: it records what it would have done and changes nothing.

## Watch them fire

Run one message with an e-mail address and one that tries a prompt injection, and print only the guard notes from each trace:

```python title="main.py"
--8<-- "docs_src/tutorial/guardrails/main.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed
   1 note    -                 harness.guard (guard_fired): guardrails.input[pii] redact
completed
   2 note    -                 harness.guard (guard_shadow): guardrails.input[injection] would block
```

The first run's e-mail address became `[EMAIL]` before the model saw it. The second run's injection guard *would* have blocked it, but it is in shadow mode, so the run went on and the trace says so. Neither note holds the content: only the guard's name, its action and what it found (RULES R9).

## Stages

A guard runs at one of five stages, each a hook point:

| Stage | Hook point | Checks | What a block does |
| --- | --- | --- | --- |
| `input` | `input.before` | The run's input | Stops the run |
| `context` | `context.after` | Each retrieved item ([Retrieval](context.md)) | Drops that item; the run goes on |
| `tool_result` | `tool.after` | A tool's output ([Tools](tools.md)) | Stops the run |
| `output` | `output.before` | A candidate final output | Stops the run; `repair` asks the model again |
| `stream` | `stream.chunk` | Each streamed text chunk | Cuts the stream |

A task can also have guards of its own, under `tasks.<task>.guardrails`, with the same shape. [Retrieval and memory](context.md) adds one.

## Actions

A provider proposes an action. The spec's `action` replaces it whenever the provider flags something, and a provider that finds nothing always allows.

| Action | Effect |
| --- | --- |
| `allow` | Continue |
| `redact` | Continue with the redacted content. A provider that can't redact blocks instead |
| `repair` | Ask the model to fix its answer. Output stage only; elsewhere it blocks |
| `escalate` | End the run `escalated`, for a person to handle |
| `require_approval` | Suspend for a person ([Approvals](approvals.md)) |
| `block` | Stop the run, with the code `guard_blocked` (drop the item, at the context stage) |
| `log_only` | Record what would have happened, change nothing: the same as `mode: log_only` |

## Shadow mode

A new guard can block good traffic you didn't think of. So new guards start in shadow mode (RULES R8): they record a `guard_shadow` note instead of acting. When the evidence shows the guard is right, you promote it with a one-line, reviewed change: `mode: log_only` becomes `mode: enforce`.

The CLI adds guards that way:

```console
$ uv run harnessweaver add guard injection.heuristic harness.yaml
added guardrails.input[injection-heuristic] (injection.heuristic) in shadow mode (mode: log_only)
  promote it with mode: enforce once the eval shadow report backs it (R8)
```

[Evals](evals.md) shows the evidence: how often each shadow guard would fire, with its false positives and misses. Guards you write in a spec yourself enforce by default, so a baseline enforces exactly what it says ([ADR-0008](../adr/0008-guard-modes.md)).

## How the guards run

- **One middleware per guard.** Guards run in list order, redactions chain from one guard to the next, and the most severe action wins.
- **Structured content.** Every string in a structured input or output (a JSON object, a list) is checked, object keys included, and redactions are written back in place. Keys that redact to one name stay distinct (`[EMAIL]`, `[EMAIL]#2`), so no entry is lost. Field names of a typed output are checked too: a guard that flags one sends the output to repair, so word `topic.deny` and `regex.deny` patterns with your field names in mind.
- **Bands.** A guard's band comes from the layer that declared it: org profiles give `baseline`, built-in profiles `platform`, your spec `app`, and a task's own guards `task`. Inbound hooks run the baseline first. [The hook bus](../concepts/hook-bus.md) explains the order.
- **Parallel groups.** Consecutive guards with `parallel: true` in the same band run concurrently.
- **Failure.** A guard that raises or runs past its `timeout` blocks when `fail_mode: closed` (the default), and is skipped, with a note, when `open`. Baseline guards must fail closed (RULES R2).
- **Where.** `where: sidecar` runs a guard's provider in the [harnessd sidecar](../advanced/sidecar.md#guards-that-run-in-the-sidecar), for providers that exist only in Python or need heavy dependencies.

## Built-in guards

| Guard | Finds | Proposes |
| --- | --- | --- |
| `pii.regex` | E-mail addresses, phone numbers, card numbers, US social security numbers, IP addresses. Its findings mark the run as holding private data | `redact` |
| `secrets.scan` | Private keys, cloud and API keys, JWTs, `password=...` assignments | `block` |
| `injection.heuristic` | Phrases typical of prompt injection. Cheap and easy to evade: pair it with the other controls | `block` |
| `regex.deny` | Your own patterns | `block` |
| `size.limit` | Content over a size; its redaction truncates | `block` |
| `topic.deny` | Denied topics, by keywords | `block` |
| `grounded.citations` | Sentences that don't cite retrieved context ([Retrieval](context.md)) | `repair` |
| `llm.judge` | Content that fails your criteria, judged by a model. It can only make a decision stricter (RULES R3) | `block` |

Every guard's settings are in [Providers](../reference/providers.md#guards). To write your own, see [Providers and ports](../advanced/providers.md#example-a-guard).

## Recap

- Guards check content at five stages: `input`, `context`, `tool_result`, `output` and `stream`.
- A guard redacts, repairs, escalates, asks for approval or blocks, and every firing is a note in the trace, without the content.
- New guards start in **shadow mode** and are promoted to `enforce` once evals back them.
