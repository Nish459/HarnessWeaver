# Acme's org baseline

[acme-baseline.yaml](acme-baseline.yaml) is the profile Acme's platform security
team publishes. Every Acme app extends it:

```yaml
extends: ["org://acme-baseline@^1", "profile://rag"]
```

and finds it through `HARNESSWEAVER_PROFILE_PATH` (or `--profile-dir`)
pointing at this directory.

| It sets | So that |
| --- | --- |
| `plugins.allow` (locked) | Only reviewed plugins load (S8) |
| `require_level` | Internal tools reach L1, customer-facing apps L2, apps that take actions L3 |
| `observability.capture_content: false` (locked) | No prompt or output content in telemetry (R9) |
| `guardrails.input[base-pii]`, `guardrails.output[base-secrets]` (locked) | PII is redacted and secrets are blocked in every app (R1) |
| `tools.require_manifest: true`, `tools.approval_by_risk` (locked) | No tool runs without a manifest (S2), and high- and critical-risk calls wait for a human |
| `bounds` on budgets | No app or caller goes over the org's caps; a value out of bounds fails loading (R10) |

```mermaid
flowchart LR
    D[defaults] --> P["profile://rag"] --> O["org://acme-baseline@^1<br/>locks + bounds"] --> A[harness.yaml] --> E["harness.prod.yaml"]
    O -.->|a later layer changes a lock| X[LockViolation at load]
```

Examples 02 and 03 extend it (*planned*). Its tests, in [tests/](tests/test_acme_baseline.py),
show each lock and bound failing loading when an app tries to get around it.
Tightening it is a breaking change and needs a new major version (V3).
