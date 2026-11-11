# Configuration

Almost everything is configured in the spec and its overlays. The environment supplies only what changes per machine or must stay secret: which overlay applies, where org profiles live, and credentials.

## Environment variables

| Variable | Read by | Meaning |
| --- | --- | --- |
| `HARNESSWEAVER_ENV` | the loader, the CLI, harnessd, `@harnessweaver/core` | The overlay to apply: `prod` applies `harness.prod.yaml` next to the spec. A missing overlay file is not an error. `-e`/`--env` and `load(env=...)` override it |
| `HARNESSWEAVER_PROFILE_PATH` | the loader | Directories searched for `org://` profiles, separated like `PATH` (`:` on Linux and macOS, `;` on Windows). Searched before `.harness/profiles` next to the spec, and the first directory holding a name owns it. `--profile-dir` and `profile_dirs=` add more |
| `HARNESSWEAVER_TEST_MODE` | live providers | `1` makes every live provider refuse to call out: model providers, `http` tools, webhooks, the email channel, remote guards, the OTLP exporter, `SidecarClient` (R14). Set by `harnessweaver test` |
| `HARNESSD_TOKEN` | harnessd; clients through `sidecar.token_env` | The bearer token. harnessd refuses to start without it; `--token-env` names another variable |
| `HARNESSD_IMAGE` | the dev stack's Compose file | The harnessd image (default `harnessd:dev`) |
| `HARNESSWEAVER_UPSTREAM_<NAME>` | the generated LiteLLM config | The provider model behind gateway model `<NAME>`, in the gateway's environment |
| The variable in `models.api_key_env` | `openai.chat`, `anthropic.messages` | The API key (default `OPENAI_API_KEY` for `openai.chat`; the Anthropic SDK's own resolution otherwise). Never put keys in a spec (S1) |
| The variables in `headers_env` | `http` tools, the `webhook` approval channel | Header values, such as an `Authorization` token |
| `HARNESSWEAVER_EMAIL_LOGIN` | the `email` approval channel | SMTP login (default variable name; override with `login_env`) |
| `HARNESSWEAVER_EMAIL_PASSWORD` | the `email` approval channel | SMTP password (default variable name; override with `password_env`) |
| `OTEL_EXPORTER_OTLP_*` | `otel.sdk`'s exporters | The standard OpenTelemetry exporter settings |
| `LITELLM_MASTER_KEY`, provider keys | the LiteLLM gateway | Set in the gateway's environment, not the app's |

## Environments with overlays

One base spec, and one overlay per environment that changes only what differs:

```yaml
# harness.yaml: what every environment shares
models:
  provider: openai.chat
  base_url: http://localhost:4000
  api_key_env: LITELLM_API_KEY
  default: fast
  aliases: { fast: fast-chat }
state: { use: memory }
```

```yaml
# harness.prod.yaml
models:
  base_url: http://litellm.internal:4000
  aliases: { fast: fast-chat-prod }
state: { use: sqlite, path: /var/lib/app/harness.db }
observability: { configure_sdk: true, exporter: otlp, endpoint: http://otel-collector:4318 }
```

```yaml
# harness.offline.yaml: tests and demos, no network
models:
  provider: scripted
  replies: [{ text: "offline answer" }]
```

An overlay holds sections only: no `metadata`, `extends`, `locks`, `bounds` or `require_level`. It is merged after the app spec and is still bound by the baseline's locks and bounds, so `spec validate -e prod` in CI catches an overlay that breaks one.

## Files

| Path (next to the spec) | Contains | Commit it? |
| --- | --- | --- |
| `harness.yaml`, `harness.<env>.yaml` | The spec and its overlays | Yes |
| `prompts/` (`prompts.dir`) | Versioned prompts | Yes |
| `tools/*.tool.yaml` (`tools.manifests`) | Tool manifests, with pinned digests | Yes |
| `evals/*.yaml` | Eval datasets | Yes |
| `policy_tests.yaml` | Policy test cases | Yes |
| `.harness/baselines/` | Eval baselines | Yes |
| `.harness/profiles/` | Org profiles, when not on the profile path | If the app owns them |
| `.harness/state.db` (default `sqlite` path, relative to the working directory) | Runs, checkpoints, recordings, samples | No |
| `.harness/dev/` | The generated local dev stack, with secrets in `.env` | No (it ignores itself) |
| `gateway/` | Generated gateway configs, if you keep them as golden files | Yes |

## Logs

HarnessWeaver's logs are off until the app enables them: `logger.enable("harnessweaver")` for the core, and `logger.enable("harnessweaver_<plugin>")` for a plugin. The library never adds a loguru sink. See [Observability](../tutorial/observability.md#logs).
