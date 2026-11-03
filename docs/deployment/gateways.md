# Gateways and the dev stack

Some apps call models and tools straight through a gateway, with no HarnessWeaver SDK. They can still get controls from the same spec: `harnessweaver gateway litellm` writes a [LiteLLM Proxy](https://docs.litellm.ai/docs/simple_proxy) config, and `harnessweaver gateway mcp` writes a neutral tool allow-list for an MCP gateway. `harnessweaver dev` writes a whole local stack around them.

```bash
uv run harnessweaver gateway litellm harness.yaml -o gateway/litellm.yaml
uv run harnessweaver gateway mcp harness.yaml -o gateway/tools.yaml
uv run harnessweaver dev harness.yaml --up
```

Examples 02 and 03 keep both configs under `gateway/`, and their tests compare them with freshly generated ones (golden files), so a spec change that changes the gateway is reviewed.

## gateway litellm

| From the spec | To the LiteLLM config |
| --- | --- |
| `models.aliases`, `models.default`, `allowed_aliases` | `model_list`: one entry per gateway model, its provider model read from `HARNESSWEAVER_UPSTREAM_<NAME>`; and `router_settings.model_group_alias`, so apps can ask for the aliases |
| The gateway owns retries (RULES R5) | `router_settings.num_retries: 2` |
| The longest run deadline | `router_settings.timeout`, so the gateway gives up when the harness does |
| `observability.capture_content: false` (R9) | `litellm_settings.turn_off_message_logging: true` |
| `observability.exporter: otlp` | The `otel` callback and its endpoint |
| Tool manifests | A `tool_permission` guardrail on every request: allow the tools on the allow-list (with their arguments' `pattern` or `enum` as regexes), deny the rest |
| Provider keys (S1) | `master_key: os.environ/LITELLM_MASTER_KEY`; provider keys stay in the gateway's environment |

```yaml
# Generated for Example 03 (abridged)
model_list:
- model_name: fast-chat
  litellm_params:
    model: os.environ/HARNESSWEAVER_UPSTREAM_FAST_CHAT
router_settings:
  num_retries: 2
  model_group_alias: { fast: fast-chat, strong: strong-chat }
  timeout: 300
litellm_settings:
  turn_off_message_logging: true
guardrails:
- guardrail_name: harnessweaver-tools
  litellm_params:
    guardrail: tool_permission
    mode: post_call
    default_on: true
    rules:
    - id: allow-lookup_order
      tool_name: ^lookup_order$
      decision: allow
      allowed_param_patterns:
        order_id: ^A-[0-9]{4}$
    - id: withhold-email_customer
      tool_name: ^email_customer$
      decision: deny
```

**Which provider serves a gateway model is the gateway owner's choice**, not the app's: set `HARNESSWEAVER_UPSTREAM_<NAME>` in the gateway's environment, where `<NAME>` is the gateway model's name in upper case with other characters as `_` (`fast-chat` becomes `HARNESSWEAVER_UPSTREAM_FAST_CHAT`), to a LiteLLM model name such as `anthropic/claude-haiku-5-5`.

## gateway mcp

Writes a `ToolAllowList` (schema `tool-allow-list`): for each allowed tool, its MCP `server`, `definition_digest` and `scopes`; and every withheld tool with the reason. MCP gateways differ, so the format is neutral; turn it into your gateway's configuration.

## What a gateway may let through

A gateway can't see a run: it can't wait for a person, track what a run has read, or tell tenants apart. So a tool is allowed at a gateway only when its manifest asks for nothing that needs a run. A tool is **withheld** (denied at the gateway and listed with the reason, to run through the harness or harnessd instead) when it:

- can need approval: its manifest `approval`, `tools.approval_by_risk`, or a task's `approvals.tools`;
- has `egress`, because the trifecta check needs what the run has seen (S3);
- is enabled for some tenants only;
- has rate limits;
- is disabled, or its pinned digest doesn't match its definition (S2).

Policy rules, budgets, guards and approvals stay with the harness. Withholding fails closed and says why.

## The local dev stack

`harnessweaver dev [SPEC] [--up]` writes `.harness/dev/` next to the spec:

| File | Contains |
| --- | --- |
| `compose.yaml` | LiteLLM, an OpenTelemetry collector, Langfuse (web, worker, Postgres, ClickHouse, Redis, MinIO) and harnessd |
| `litellm.yaml` | The `gateway litellm` config for this spec and overlay |
| `otel-collector.yaml` | A collector that receives OTLP and forwards traces to Langfuse over OTLP HTTP |
| `.env` | Local secrets, generated once and kept: the LiteLLM master key (also set as the app's key variable), the harnessd token, database passwords, Langfuse keys and a login. Empty lines for the provider keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) and each `HARNESSWEAVER_UPSTREAM_*` |

harnessd runs from the image in `$HARNESSD_IMAGE` (default `harnessd:dev`), so build it first, from the repository root:

```bash
docker build -f deploy/harnessd/Dockerfile -t harnessd:dev .
```

Fill in a provider key and the upstream model names in `.env`, then `--up` (or `docker compose up -d` in that folder) starts it:

| Service | On the host |
| --- | --- |
| LiteLLM Proxy | `http://127.0.0.1:4000` |
| OTLP (the collector) | `127.0.0.1:4317` (gRPC), `127.0.0.1:4318` (HTTP) |
| harnessd | `http://127.0.0.1:7070` |
| Langfuse | `http://127.0.0.1:3000` |

- harnessd and the collector share LiteLLM's network namespace, so a spec's `localhost` URLs work on your machine and inside the containers alike.
- Images are pinned by digest (RULES S5), and every port is published on 127.0.0.1 only (S6).
- `.harness/dev/` holds its own `.gitignore` (`*`), so nothing in it is committed; never commit `.env` anywhere.
- `--profile-dir` folders are mounted read-only into harnessd's container and put on its profile path.

Point your app at the gateway (`models.base_url: http://localhost:4000`, the key variable from `.env`) and at the collector (`observability.endpoint: http://localhost:4318`, with `configure_sdk: true`), and its traces appear in Langfuse.
