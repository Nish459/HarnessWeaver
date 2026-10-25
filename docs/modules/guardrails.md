# Guardrails

Guards check content at five stages of a run: the input, retrieved context, tool results, the final output, and each streamed chunk. Each guard is a `Guardrail` provider that proposes an action (allow, redact, block, ...); the spec can override the action, run the guard in shadow mode, run it in parallel with others, or run it in the sidecar.

```yaml
extends: ["profile://rag"]            # the profile's guards come first
guardrails:
  input:
    - { id: pii, use: pii.regex, action: redact, entities: [EMAIL, PHONE, CREDIT_CARD] }
    - { id: injection, use: injection.heuristic, action: block, threshold: 0.5 }
    - { id: topics, use: topic.deny, topics: { legal: [lawsuit, attorney] }, mode: log_only }
  context:
    - { id: context-injection, use: injection.heuristic, action: block }   # drops the item
  tool_result:
    - { id: tool-secrets, use: secrets.scan, action: redact }
  output:
    - { id: citations, use: grounded.citations, min_supported: 1.0, action: repair }
    - { id: secrets, use: secrets.scan, action: block }
  stream:
    - { id: stream-secrets, use: secrets.scan, action: block }             # cuts the stream
```

## Stages

| Stage | Hook point | Checks | Typical guards | A block |
| --- | --- | --- | --- | --- |
| `input` | `input.before` | The run's input, or what `s.guard("input", ...)` passes | size, regex, `pii.regex`, then `injection.heuristic`, `topic.deny` | Stops the run |
| `context` | `context.after` | Each retrieved item | `injection.heuristic` | Drops that item; the run goes on |
| `tool_result` | `tool.after` | A tool's output, after the governor's own sanitizing | `secrets.scan`, PII redaction | Stops the run |
| `output` | `output.before` | A candidate final output | `secrets.scan`, `grounded.citations`, `llm.judge` | Stops the run; `repair` asks the model again |
| `stream` | `stream.chunk` | Each streamed text chunk | `secrets.scan` | Cuts the stream |

## How the pipeline runs

([fixtures suite `guards`](../extending/contracts.md#conformance-fixtures), the same in Python and TypeScript)

- **One middleware per guard.** Each guard is installed as its own middleware on its stage's hook, so guards run in list order (profile and baseline guards first), redactions chain from one guard to the next, and the most severe action wins.
- **Structured payloads.** Every string in a structured input or output (a JSON object, a list) is checked, and redactions are written back in place.
- **Parallel groups.** Consecutive `parallel: true` guards in the same band run concurrently as one group; their redactions are then applied in list order.
- **Bands.** A guard's band comes from the layer that declared it: org profiles give `baseline`, built-in profiles `platform`, the app `app`, and a task's own `guardrails` `task`. Baseline guards must fail closed (RULES R2).
- **Fail mode and timeout.** A guard that raises or runs past its `timeout` blocks when `fail_mode: closed` (the default), and is skipped, with a trace note, when `open`.

## Actions

A provider proposes an action; the spec's `action` replaces it whenever the provider flags something (a provider that finds nothing always allows).

| Action | Effect | Notes |
| --- | --- | --- |
| `allow` | Continue | |
| `redact` | Continue with the redacted content | Asking to redact what a provider can't redact blocks instead |
| `repair` | Ask the model to fix its answer | Output stage only; anywhere else it blocks |
| `escalate` | End the run `escalated` | |
| `require_approval` | Suspend for a human (or escalate in a session) | An output a human already approved passes |
| `block` | Stop the run (drop the item at the context stage) | Code `guard_blocked` |
| `log_only` | Record what would have happened, change nothing | Same as `mode: log_only` |

## Shadow mode

`mode: log_only` makes a guard record what it *would* have done, without enforcing it (RULES R8). New guards should start this way: `harnessweaver add guard <provider>` adds them in shadow mode, `harnessweaver doctor` lists them, and `harnessweaver eval run` reports how often each would fire, with its false positives and misses against your eval cases. Promote a guard with a reviewed one-line change to `mode: enforce`. See [Evals](evals.md#shadow-guard-report).

Guards declared in a spec default to `mode: enforce`, so a baseline enforces exactly what it says ([ADR-0008](../adr/0008-guard-modes.md)).

## Firing notes

A guard whose verdict isn't `allow` adds a `harness.guard` note to the trace: code `guard_fired`, or `guard_shadow` in shadow mode, with the guard's full name (`guardrails.input[pii]`, `tasks.<task>.guardrails.output[<id>]`), its action and its finding types, never the content (R9, [ADR-0036](../adr/0036-dry-runs-and-guard-notes.md)). The `guard_fired` grader, `doctor` and the shadow-guard report all use these names.

## Approved outputs

An output a human approved reaches `output.before` with the approval attached. A guard's `require_approval` on it is answered: the guard lets it through and adds a `guard_approved` note naming the guard and the approver (R13). The approval answers nothing else: `block`, `escalate` and `repair` still apply, redactions still chain, and shadow guards still record. A rejection is never a grant.

## Where a guard runs

`where: local` (the default) runs the provider in the app. `where: sidecar` runs it in harnessd at `sidecar.url`, for providers that exist only in Python (or need a heavy dependency you'd rather keep out of the app):

```yaml
sidecar: { url: http://127.0.0.1:7070, token_env: HARNESSD_TOKEN }
guardrails:
  input:
    - { id: pii, use: presidio.pii, action: redact, where: sidecar }
```

The guard keeps its place on the bus, its action, mode, fail mode and timeout; only its provider's check is posted to harnessd. A sidecar that can't answer is a provider failure, which the guard's fail mode turns into a block or a pass (R2). `plugins.allow` applies to the provider's name on both sides. See [harnessd](../tooling/sidecar.md#guards-that-run-in-the-sidecar).

## Built-in guards

All are deterministic except `llm.judge`. Their patterns are part of the contract, written in regex syntax Python and TypeScript share.

### pii.regex

Finds e-mail addresses, phone numbers, card numbers (Luhn-checked), US social security numbers and IP addresses, and redacts them. Its findings are marked **private**, so a run where it finds PII is marked private wherever the guard runs (the trifecta check reads this).

| Setting | Default | Meaning |
| --- | --- | --- |
| `entities` | all | Any of `EMAIL`, `CREDIT_CARD`, `SSN`, `PHONE`, `IP_ADDRESS` |
| `replacement` | `[{entity}]` | `{entity}` is replaced by the entity name, so `ann@example.com` becomes `[EMAIL]` |

Proposes `redact`. Stages: all.

### secrets.scan

Finds credentials: private keys, AWS access keys, GitHub, Slack, Anthropic and OpenAI keys, Google API keys, JWTs, and credential assignments such as `password=...`.

| Setting | Default | Meaning |
| --- | --- | --- |
| `kinds` | all | Any of `private_key`, `aws_access_key`, `github_token`, `slack_token`, `anthropic_key`, `openai_key`, `google_api_key`, `jwt`, `credential_assignment` |
| `replacement` | `[SECRET]` | Used with `action: redact` |

Proposes `block`. Stages: all.

### injection.heuristic

Scores phrases typical of prompt injection (`ignore previous instructions`, requests to reveal the system prompt, role overrides, fake system messages, exfiltration requests) and flags content whose score reaches the threshold. It is cheap and **easy to evade**: pair it with the trifecta check, untrusted labels and approvals, and add a model-based detector when the stakes need one.

| Setting | Default | Meaning |
| --- | --- | --- |
| `threshold` | `0.5` | The score that flags content |

Proposes `block`. Stages: `input`, `context`, `tool_result`.

### regex.deny

Flags content matching any of your patterns.

| Setting | Default | Meaning |
| --- | --- | --- |
| `patterns` | required | Regular expressions (the syntax Python and JavaScript share) |
| `ignore_case` | `false` | Match regardless of case |
| `replacement` | `[REDACTED]` | Used with `action: redact` |

Proposes `block`. Stages: all.

### size.limit

Flags content over a size. Its redaction truncates.

| Setting | Default | Meaning |
| --- | --- | --- |
| `max_chars` | none | Characters (code points) |
| `max_bytes` | none | UTF-8 bytes |

Proposes `block`. Stages: all.

### topic.deny

Flags content that mentions denied topics, by whole-word keywords, ignoring case.

| Setting | Default | Meaning |
| --- | --- | --- |
| `topics` | required | A map of topic name to keywords: `{legal: [lawsuit, attorney]}` |
| `replacement` | `[REDACTED]` | Used with `action: redact` |

Proposes `block`. Stages: `input`, `output`.

### grounded.citations

Checks that the output's sentences (ending at `.`, `!` or `?` and a space, or a line break) of at least `min_words` words cite a context item in square brackets, like `[help-refunds]`, and that each citation names an item the run actually retrieved ([ADR-0032](../adr/0032-grounded-citations.md)). Proposes `repair` (the model is asked to cite); set `action: escalate` to send uncited answers to a person instead.

| Setting | Default | Meaning |
| --- | --- | --- |
| `min_supported` | `0.9` | The share of sentences that must cite |
| `min_words` | `4` | Shorter sentences need no citation |
| `require_known` | `true` | Citations must name items the run kept |
| `pattern` | `\[([A-Za-z0-9_.:#/-]+)\]` | How a citation looks; group 1 is the item id |

Stages: `output`.

### llm.judge

Asks a model whether the content meets your criteria. The call is governed and budgeted like any other model call, and the judge's own explanation isn't kept (R9). It is probabilistic, so it can only make a decision stricter (R3).

| Setting | Default | Meaning |
| --- | --- | --- |
| `criteria` | required | What acceptable content looks like |
| `model` | `models.default` | The model alias for the judge |

Proposes `block` when the content fails. Stages: `input`, `output`.

## Writing your own guard

A guard is a `Guardrail` provider: a class with a config model and an async `check(content, env)` that returns a `GuardResult`.

```python
from pydantic import BaseModel, ConfigDict
import harnessweaver as hw


class AccountIdsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prefix: str = "ACCT-"


@hw.provider(port="Guardrail", name="acme.account_ids", config=AccountIdsConfig,
             stages=["input", "tool_result", "output"], deterministic=True, latency_class="fast")
class AccountIds:
    """Redacts Acme account numbers."""

    def __init__(self, config: AccountIdsConfig) -> None:
        self.prefix = config.prefix

    async def check(self, content: str, env: hw.Envelope) -> hw.GuardResult:
        if self.prefix not in content:
            return hw.GuardResult.allow()
        redacted = content.replace(self.prefix, "[ACCOUNT]-")
        return hw.GuardResult.redact(redacted, findings=(hw.Finding(type="account_id"),))
```

`GuardResult` has `allow()`, `redact(content, findings=..., reason=...)`, `block(reason, findings=...)`, `repair(...)`, `escalate(...)` and `require_approval(...)`. A `Finding` has a `type`, optional `start`, `end` and `score`, and `private: true` when it is personal data. Reasons and findings name types, never the content (R9). Register the class in your plugin and use it as `use: acme.account_ids`. The conformance suite checks it for determinism, timeouts, latency and leaks ([Conformance](../extending/conformance.md)). See [Providers and ports](../extending/providers.md) and, for TypeScript, `defineProvider({ port: "Guardrail", ... })` in [TypeScript](../tooling/typescript.md#plugins).
