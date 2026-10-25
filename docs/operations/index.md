# Operations

Running HarnessWeaver in production: where the pieces go, how they are configured, how they are secured, how versions move, and what to do when a spec doesn't load.

| Page | Covers |
| --- | --- |
| [Deployment](deployment.md) | The three deployment shapes (in process, sidecar, gateway only), the services around them, and a production checklist |
| [Configuration](configuration.md) | Environment variables, overlays per environment, files the harness reads and writes |
| [Security](security.md) | The threat model and its controls, the invariants an operator can rely on, and hardening |
| [Versioning](versioning.md) | How contracts, packages and profiles are versioned, and how to upgrade safely |
| [Troubleshooting](troubleshooting.md) | Every load error and common run-time block, with causes and fixes |

The short version:

1. Run models behind a **gateway** (LiteLLM Proxy) that holds the provider keys and owns retries.
2. Keep the **org baseline** in one versioned place every app extends, and lock what must not change.
3. Give each environment an **overlay** (`harness.prod.yaml`), selected by `HARNESSWEAVER_ENV`.
4. Use a **durable state store** when runs wait for approval.
5. Send **traces** to an OpenTelemetry collector; keep content capture off.
6. Gate every change in **CI**: `spec validate`, tests, `eval run`, `policy test`, and `spec diff` in the pull request.
