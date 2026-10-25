# Examples

The repository has four example apps and the org baseline they share. Each one runs offline (`HARNESSWEAVER_ENV=offline` swaps the model for a scripted one), has tests that CI runs end to end (RULES T6), and has a README with a diagram of what happens in one request. Together they cover every adoption level and every integration style.

| Example | Level | Style | Shows |
| --- | --- | --- | --- |
| [01 Invoice extraction](#example-01-invoice-extraction) | L1 | Run, plus Wrap for L0 | Typed output with repair, PII redaction, a secrets check, budgets, and `instrument()` in three lines |
| [Org baseline](#the-org-baseline) | - | - | The profile a platform team publishes: locks, bounds and a required level per risk tier |
| [02 Support assistant](#example-02-support-assistant) | L4 | Session | Routing, ACL-checked retrieval, injection guards, citations, evals, the baseline's locks |
| [03 Refund agent](#example-03-refund-agent) | L4 | Run and Wrap, with Pydantic AI | Governed tools, policy, the lethal trifecta, approvals, a red-team eval set, an app's own plugin |
| [04 One spec, every language](#example-04-one-spec-every-language) | L4 | Session in TypeScript, HTTP | Example 02's spec from TypeScript and through harnessd, with the same answers both ways, and a `curl` walkthrough |

All commands run from the repository root after `uv sync --all-packages`.

## Example 01: invoice extraction

An accounts payable team turns the text of supplier invoices into a typed `Invoice`. The app calls `harness.run()` and nothing else: no retry loop, no error handling around the model, no tracing code.

```bash
HARNESSWEAVER_ENV=offline uv run python examples/01_invoice_extraction/run.py
HARNESSWEAVER_ENV=offline uv run python examples/01_invoice_extraction/l0_instrument.py
uv run pytest examples/01_invoice_extraction -q
```

- **Spec:** extends `profile://extraction`; one `direct` task with an `output` model, a prompt, a budget and a cel-lite business rule.
- **Offline:** the scripted model's first answer is invalid, so every run shows a repair: the validation errors go back to the model, and the second answer passes.
- **L0:** `l0_instrument.py` governs an existing OpenAI client in three lines, against a stand-in gateway, so the redaction and budget apply to calls the app already makes.

[Source and README](https://github.com/Wise-DreamerZ/HarnessWeaver/tree/main/examples/01_invoice_extraction)

## The org baseline

`examples/_org/acme-baseline.yaml` is the profile Acme's platform security team publishes and every Acme app extends with `extends: ["org://acme-baseline@^1", ...]`. Apps find it through `HARNESSWEAVER_PROFILE_PATH`, or `--profile-dir examples/_org` on the CLI.

| It sets | So that |
| --- | --- |
| `plugins.allow` (locked) | Only reviewed plugins load |
| `require_level` | Internal tools reach L1, customer-facing apps L2, apps that take actions L3 |
| `observability.capture_content: false` (locked) | No prompt or output content in telemetry |
| `guardrails.input[base-pii]`, `guardrails.output[base-secrets]` (locked) | PII is redacted and secrets are blocked in every app |
| `tools.require_manifest`, `tools.approval_by_risk` (locked) | No tool runs without a manifest, and high- and critical-risk calls wait for a human |
| `bounds` on budgets | No app or caller goes over the org's caps; a value outside them fails loading |

Its tests show each lock and bound failing loading. See [Layers, locks and bounds](../spec/layers.md) for how this works. [Source and README](https://github.com/Wise-DreamerZ/HarnessWeaver/tree/main/examples/_org)

## Example 02: support assistant

Acme's support assistant answers customers' questions from the help center and cites the articles it used. The app owns the flow (route, retrieve, answer) and calls the harness for each step.

```bash
HARNESSWEAVER_ENV=offline uv run python examples/02_support_rag/run.py
uv run harnessweaver eval run examples/02_support_rag/harness.yaml -e offline --profile-dir examples/_org
uv run pytest examples/02_support_rag -q
```

- **Routing:** a rules stage catches outages exactly, a lexical stage decides the rest when confident, and a default answers otherwise.
- **Retrieval:** help-center articles carry ACLs; the harness re-checks each one, so one customer's contract never reaches another customer's answer.
- **Injection:** a poisoned article is dropped by the context guard before the model sees it; an injected question is blocked at input.
- **Citations:** `grounded.citations` asks for a repair when a sentence cites nothing the run retrieved.
- **Baseline:** the tests load overlays that try to switch content capture on, disable the PII guard and allow an unreviewed plugin; each fails with `LockViolation`.
- **Gateway:** `gateway/litellm.yaml` is `harnessweaver gateway litellm` output, kept as a golden file.

[Source and README](https://github.com/Wise-DreamerZ/HarnessWeaver/tree/main/examples/02_support_rag)

## Example 03: refund agent

A Pydantic AI agent decides what to do with a refund request; the harness decides what it may do.

```bash
HARNESSWEAVER_ENV=offline uv run python examples/03_refund_agent/run.py
HARNESSWEAVER_ENV=offline uv run python examples/03_refund_agent/wrap.py
uv run harnessweaver eval run examples/03_refund_agent/harness.yaml -e offline --profile-dir examples/_org
uv run harnessweaver policy test examples/03_refund_agent/harness.yaml --cases examples/03_refund_agent/policy_tests.yaml --profile-dir examples/_org
uv run pytest examples/03_refund_agent -q
```

- **Tools:** `lookup_order` (reads customer data), `refund_payment` and `email_customer` (both with external egress), each with a pinned manifest. Every call passes the nine-step governor.
- **Policy and approvals:** deterministic rules deny refunds over $1,000 and refunds by contractors; the manifest sends refunds over $100 to a human with the `finance` role, and `approve()` resumes the agent where it stopped.
- **Trifecta:** the spec sets `tools.trifecta: block`, so once the agent has read untrusted content and customer data, no e-mail goes out.
- **Plugin:** `refunds/acme.py` is the app's own plugin (namespace `acme`, loaded through `plugins.local`): a middleware that holds weekend refunds for approval, and a guard that redacts account numbers before the model sees them.
- **Evals:** a golden set and a red-team set, whose cases must end `blocked`.
- **Styles:** `run.py` uses the `pydantic_ai.agent` runner; `wrap.py` governs an agent the app already has with `harness.wrap()`.

[Source and README](https://github.com/Wise-DreamerZ/HarnessWeaver/tree/main/examples/03_refund_agent)

## Example 04: one spec, every language

Example 02's own `harness.yaml`, unchanged, served to TypeScript and to any language over HTTP.

```bash
pnpm -C typescript install && pnpm -C typescript build
HARNESSWEAVER_ENV=offline node examples/04_polyglot_typescript/dist/run.js
pnpm -C examples/04_polyglot_typescript test        # starts harnessd itself
```

- **TypeScript, in process:** `src/support.ts` ports Example 02's flow to `@harnessweaver/core`; the model is a Vercel AI SDK model governed by `wrapModel`.
- **Through harnessd:** the same spec served by the sidecar; the tests require the TypeScript app and harnessd to give the same answers to Example 02's golden questions.
- **curl:** the README's walkthrough shows each call a Go, Java or Ruby app would make, and the tests run it as written.

[Source and README](https://github.com/Wise-DreamerZ/HarnessWeaver/tree/main/examples/04_polyglot_typescript)

## Templates

`harnessweaver init` starts a project of your own from one of five templates (`extraction`, `rag`, `agent`, `workflow`, `chat`), each with an offline overlay, evals and tests that pass. See [Templates](../tooling/templates.md).
