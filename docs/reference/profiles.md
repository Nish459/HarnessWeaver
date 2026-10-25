# Built-in profiles

A profile is a reusable partial spec. The core ships six: `defaults`, which is always the first layer of every spec, and five starting points for common kinds of app, which a spec selects with `extends: ["profile://<name>"]`. Built-in profiles are merged before org profiles, so an org baseline can tighten them ([Layers](../advanced/layers.md)). Their guards run in the `platform` band.

Change a profile's guard by restating its id in your spec (`{ id: rag-injection, threshold: 0.7 }`), switch it off with `enabled: false`, or add your own guards after it. None of the built-in profiles lock anything.

| Profile | For | Adds |
| --- | --- | --- |
| [`defaults`](#defaults) | Every spec | Safe, minimal settings: no telemetry export, no content capture, manifests required, one repair, `cel_lite` policy, in-memory approvals and state |
| [`extraction`](#extraction) | Typed extraction | PII redaction on input, secrets check on output, one repair then escalate, a 1 minute deadline |
| [`rag`](#rag) | Retrieval-augmented answers | PII redaction and injection checks on input, injection check on retrieved context, secrets check on output, a 30 second deadline |
| [`agent`](#agent) | Tool-using agents | Injection check on input, secrets redacted from tool results, secrets check on output, manifests required, 20 tool calls, a 2 minute deadline |
| [`workflow`](#workflow) | Deterministic pipelines | Secrets check on output, a 5 minute deadline |
| [`chat`](#chat) | Conversational apps | PII redaction on input, secrets check on each streamed chunk and on output, a 1 minute deadline |

## defaults

```yaml
apiVersion: harnessweaver/v1
kind: Profile
metadata: { name: defaults, version: 1.0.0, owner: harnessweaver }
observability:
  exporter: none
  capture_content: false   # R9: no raw content in telemetry
  configure_sdk: false     # R5: the app owns its OpenTelemetry setup
tools:
  require_manifest: true   # S2: no tool runs without a manifest
  max_output_bytes: 20000
validation:
  max_repairs: 1
  on_failure: block
policy:
  use: cel_lite
  default_effect: allow
approvals:
  use: memory
  timeout: 24h
  on_timeout: escalate
state:
  use: memory
require_level:
  default: L0
```

## extraction

```yaml
metadata: { name: extraction, version: 1.0.0, owner: harnessweaver }
guardrails:
  input:
    - { id: extraction-pii, use: pii.regex, action: redact }
  output:
    - { id: extraction-secrets, use: secrets.scan, action: block }
validation:
  max_repairs: 1
  on_failure: escalate
budgets:
  per_run: { deadline: 1m }
```

Used by [Example 01](../resources/examples.md#example-01-invoice-extraction) and the `extraction` template.

## rag

```yaml
metadata: { name: rag, version: 1.0.0, owner: harnessweaver }
guardrails:
  input:
    - { id: rag-pii, use: pii.regex, action: redact }
    - { id: rag-injection, use: injection.heuristic, action: block }
  context:
    - { id: rag-context-injection, use: injection.heuristic, action: block }
  output:
    - { id: rag-secrets, use: secrets.scan, action: block }
budgets:
  per_run: { deadline: 30s }
```

At the context stage a block drops the item, so a poisoned document never reaches the model while the rest of the answer goes ahead. Used by [Example 02](../resources/examples.md#example-02-support-assistant) and the `rag` template.

## agent

```yaml
metadata: { name: agent, version: 1.0.0, owner: harnessweaver }
guardrails:
  input:
    - { id: agent-injection, use: injection.heuristic, action: block }
  tool_result:
    - { id: agent-tool-secrets, use: secrets.scan, action: redact }
  output:
    - { id: agent-secrets, use: secrets.scan, action: block }
tools:
  require_manifest: true
budgets:
  per_run: { max_tool_calls: 20, deadline: 2m }
```

Used by [Example 03](../resources/examples.md#example-03-refund-agent) and the `agent` template.

## workflow

```yaml
metadata: { name: workflow, version: 1.0.0, owner: harnessweaver }
guardrails:
  output:
    - { id: workflow-secrets, use: secrets.scan, action: block }
budgets:
  per_run: { deadline: 5m }
```

Used by the `workflow` template.

## chat

```yaml
metadata: { name: chat, version: 1.0.0, owner: harnessweaver }
guardrails:
  input:
    - { id: chat-pii, use: pii.regex, action: redact }
  stream:
    - { id: chat-stream-secrets, use: secrets.scan, action: block }
  output:
    - { id: chat-secrets, use: secrets.scan, action: block }
budgets:
  per_run: { deadline: 1m }
```

The stream guard checks each chunk as it is produced, so a secret is cut before the rest of the answer streams. Used by the `chat` template.

## Org and plugin profiles

Your platform team's profiles work the same way, with three additions only profiles can make: `locks`, `bounds` and `require_level`. See [Writing an org baseline](../advanced/layers.md#writing-an-org-baseline). A plugin can ship profiles too (`hw.Plugin(profiles={"baseline": "profiles/baseline.yaml"})`), which specs select as `profile://<namespace>.<name>@<range>`; they count as org layers.
