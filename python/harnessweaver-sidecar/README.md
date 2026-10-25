# harnessweaver-sidecar

`harnessd`, the [HarnessWeaver](../../README.md) sidecar. It serves one `harness.yaml` over HTTP/JSON, so apps in any language get the same guards, routing, policy, tool governance, approvals and evals as a Python app, decided by the same core (DESIGNS No. 24, ADR-0038).

```bash
uv add harnessweaver-sidecar
export HARNESSD_TOKEN=...            # required: harnessd never runs without a token (RULES S6)
harnessd harness.yaml -e prod        # binds 127.0.0.1:7070 by default
```

`harnessweaver sidecar harness.yaml` does the same from the CLI. The full guide, with request bodies and error statuses, is [docs/tooling/sidecar.md](../../docs/tooling/sidecar.md). Options: `-e/--env` (the overlay, default `$HARNESSWEAVER_ENV`), `--profile-dir`, `--host`, `--port`, `--token-env`.

## The API

Every route except `GET /v1/health` needs `Authorization: Bearer <token>`. The full description is [contracts/openapi/harnessd.openapi.json](../../contracts/openapi/harnessd.openapi.json); [contracts/proto/harnessweaver/v1/harnessd.proto](../../contracts/proto/harnessweaver/v1/harnessd.proto) mirrors it for gRPC later.

| Route | What it does | Answer |
| --- | --- | --- |
| `GET /v1/health` | Liveness and versions | `{status, harnessd, harnessweaver}` |
| `GET /v1/spec` | The effective spec, every layer applied | `SpecInfo` |
| `GET /v1/hooks?task=` | The middleware on each hook point, in run order | lists of `HookEntry` |
| `POST /v1/guards/{stage}` | `input`, `context` or `output`: the stage's guards and middleware | `RunResult` |
| `POST /v1/guards/providers/{name}:check` | One guardrail provider (for `where: sidecar` guards) | `GuardResult` |
| `POST /v1/decisions/{router}` | A routing decision | `RunResult` (output: `Decision`) |
| `POST /v1/policy/evaluate` | The policy engine's answer | `PolicyDecision` |
| `POST /v1/tools/{name}/authorize` | The governor's verdict, as a dry run | `ToolVerdict` |
| `POST /v1/tools/{name}/sanitize` | Step 9 and `tool.after` on your own tool's result | `RunResult` (output: `ToolResult`) |
| `POST /v1/validate` | A final output against its task's type and rules | `RunResult` |
| `POST /v1/runs` | Run a task, until it ends or waits for approval | `RunResult` |
| `GET /v1/runs/{run_id}` | A run's latest state | `RunResult` |
| `POST /v1/runs/{run_id}/approvals/{approval_id}` | Answer an approval | `RunResult` |
| `POST /v1/evals/run` | An eval suite, sent inline or named from the spec's `evals` | `SuiteResult` |

Checks run as one-step sessions for the principal, tenant and task the request names: `run.start` rules, budgets and the trace apply, and a blocked check is the `RunResult`'s `status` and `error`, not an HTTP error. Other errors are `ErrorInfo` bodies (400, 401, 403, 404, 422, 502); an invalid request is described by field locations, never by its values (R9).

```bash
curl -s localhost:7070/v1/guards/input \
  -H "Authorization: Bearer $HARNESSD_TOKEN" -H "Content-Type: application/json" \
  -d '{"principal": "alice", "tenant": "acme", "content": "mail ann@example.com"}'
# {"run_id": "...", "status": "completed", "output": "mail [EMAIL]", ...}
```

## Guards that run in the sidecar

A guard declared `where: sidecar` keeps its place in the app's pipeline, but its provider runs in harnessd, so the provider needn't be installed next to the app:

```yaml
sidecar: { url: http://127.0.0.1:7070, token_env: HARNESSD_TOKEN }
guardrails:
  input:
    - { use: presidio.pii, action: redact, where: sidecar }
```

The guard's fail mode decides what happens when the sidecar can't answer (R2), and `plugins.allow` applies on both sides (S8).

## Container

```bash
docker build -f deploy/harnessd/Dockerfile -t harnessd .
docker run --rm -p 127.0.0.1:7070:7070 -e HARNESSD_TOKEN -v "$PWD:/app:ro" harnessd
```

The image is built from `uv.lock` on digest-pinned bases (S5) and runs as an unprivileged user. It includes the sidecar and the `openai`, `anthropic`, `otel` and `cel` plugins; pass `--build-arg PACKAGES="harnessweaver-sidecar ..."` for others.
