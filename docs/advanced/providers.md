# Providers and ports

A **port** is a typed interface for one capability, a `Protocol` in `harnessweaver.ports`. A **provider** is a class that satisfies it, plus a Pydantic config model so the loader can validate its settings. Decorate the class with `@hw.provider`, list it in your plugin, and specs select it with `use: <namespace>.<name>`.

```python
from pydantic import BaseModel, ConfigDict
import harnessweaver as hw


class InHousePIIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str
    entities: list[str] = ["EMAIL", "PHONE"]


@hw.provider(port="Guardrail", name="acme.pii", config=InHousePIIConfig,
             contract=">=1.0,<2", stages=["input", "tool_result", "output"],
             deterministic=True, latency_class="fast",
             sample={"endpoint": "http://pii.test"})
class InHousePII:
    """Acme's own PII detector, behind the Guardrail port."""

    def __init__(self, config: InHousePIIConfig) -> None:
        from acme_pii import Client          # imported on first use, not at plugin import (S8)
        self.client = Client(config.endpoint)
        self.entities = config.entities

    async def check(self, content: str, env: hw.Envelope) -> hw.GuardResult:
        hits = await self.client.scan(content, self.entities)
        if not hits:
            return hw.GuardResult.allow()
        findings = tuple(hw.Finding(type=h.entity, start=h.start, end=h.end, private=True) for h in hits)
        return hw.GuardResult.redact(self.client.mask(content, hits), findings=findings)
```

```yaml
guardrails:
  input:
    - { use: acme.pii, endpoint: "http://pii.internal", entities: [EMAIL], mode: log_only }
```

## @hw.provider

| Argument | Meaning |
| --- | --- |
| `port` | The port it implements (below) |
| `name` | `<namespace>.<name>`, or a bare name that gets the plugin's namespace |
| `config` | The Pydantic model the spec's settings are validated against (use `extra="forbid"`); the class is built as `Cls(config)`. Omit it for a provider without settings |
| `contract` | The contract range it supports (default `>=1.0,<2`) |
| `deterministic` | Whether the same input always gives the same answer. A `PolicyEngine` must be deterministic (RULES R3); the conformance suite checks it |
| `latency_class` | `fast` (p95 within 25 ms), `medium` (250 ms, the default) or `slow` (5 s), checked by the conformance suite |
| `stages` | For guardrails: the stages it may run at; a spec that puts it elsewhere fails to load |
| `sample` | Settings the conformance suite builds it with, required when `config` has required fields |

Settings arrive validated: the spec item's keys that HarnessWeaver doesn't own (everything but `id`, `use`, `action`, `mode`, ... for a guard) become the config model. A misspelled setting fails when the harness loads (R4).

## The ports

| Port | Methods | Selected by |
| --- | --- | --- |
| `Guardrail` | `async check(content: str, env: Envelope) -> GuardResult` | `guardrails.<stage>[].use`, `tools.judge.use` |
| `PolicyEngine` | `decide(request: PolicyRequest) -> PolicyDecision` | `policy.use` |
| `Decider` | `async __call__(request: DecisionRequest) -> Decision` | `routing.<router>.cascade[].use` (or `@hw.decider`) |
| `Embedder` | `embed(texts: Sequence[str]) -> list[list[float]]` | a `semantic` stage's `encoder` |
| `ContextProvider` | `async fetch(query: str, env: Envelope, *, limit: int | None) -> list[ContextItem]` | `context.<source>.use` |
| `Memory` | `put(namespace, key, value, *, expires_at)`, `get(namespace, key, *, now)`, `delete(namespace, key)`, `entries(namespace, *, now)` | `memory.use` |
| `ModelProvider` | `async generate(request: ModelRequest, env: Envelope) -> ModelResponse` | `models.provider` |
| `StreamingModelProvider` | `generate(...)`, and `stream(request, env)` yielding `StreamChunk`s, then the final `ModelResponse` | `models.provider` |
| `Evaluator` | `grade(sample: EvalSample) -> Grade` | a grader name in an eval dataset |
| `ApprovalChannel` | `async notify(request: ApprovalRequest, env: Envelope) -> None` | `approvals.use` |
| `StateStore` | runs, checkpoints, approval and idempotency claims, events, recordings, online samples, `aclose()` | `state.use` |
| `Sandbox` | `run(code: str, inputs: Mapping, limits: SandboxLimits) -> SandboxResult` | a `code` tool's `sandbox` |
| `Telemetry` | `configure(*, service_name, exporter, endpoint)` | `observability.configure_sdk` |

The method signatures are in `harnessweaver.ports`, typed; check whether each is sync or async there. A few notes per port:

- **Guardrail.** Return `GuardResult.allow()`, `redact(content, findings=...)`, `block(reason, findings=...)`, `repair(...)`, `escalate(...)` or `require_approval(...)`. Mark personal data findings `private=True`, so the run's `private_seen` label is set (S3). Reasons and findings name types, never the content (R9). See [Guardrails](providers.md#example-a-guard).
- **ContextProvider.** Return only what the envelope's tenant and principal may see; the harness re-checks ACLs anyway ([ADR-0030](../adr/0030-context-governance.md)).
- **ModelProvider.** Take and return only neutral contracts (R7); put a provider's own per-turn data in `ModelResponse.extensions` ([ADR-0022](../adr/0022-provider-extensions.md)); turn client errors into `ProviderError`; refuse the network in test mode (`harnessweaver.ports.network_allowed()`); report cost in `cost_usd` when the API gives it; build clients with retries off when a gateway owns them (R5).
- **PolicyEngine.** Combine `policy.rules` exactly as `decide_by_rules` does ([Policy](../tutorial/policy.md#how-rules-combine)); declare `deterministic=True`.
- **Evaluator.** Score 1 or 0 for a deterministic grader. Give the config model a `SHORTHAND: ClassVar[str | None]` naming the field a single value fills, so `{field_equals: total}` works like `{field_equals: {field: total}}`.
- **StateStore.** Pass the conformance suite's round-trip contract; `claim_idempotency` and `claim_approval` must be atomic, across processes for a store they share ([ADR-0044](../adr/0044-answers-claim-the-approval.md)).

## Functions as providers

A routing stage can be a plain async function with `@hw.decider` ([Deciders](runners-and-adapters.md#deciders)). Everything else is a class.

## Registering

List providers in your plugin's `providers=[...]`. Their names must sit in the plugin's namespace ([Plugins](plugins.md)). Then:

```bash
uv run pytest --harnessweaver-conformance=acme
```

checks every contribution ([Conformance](conformance.md)).

## Example: a guard

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

`GuardResult` has `allow()`, `redact(content, findings=..., reason=...)`, `block(reason, findings=...)`, `repair(...)`, `escalate(...)` and `require_approval(...)`. A `Finding` has a `type`, optional `start`, `end` and `score`, and `private: true` when it is personal data. Reasons and findings name types, never the content (R9). Register the class in your plugin and use it as `use: acme.account_ids`. The conformance suite checks it for determinism, timeouts, latency and leaks ([Conformance](conformance.md)). For TypeScript, see `defineProvider({ port: "Guardrail", ... })` in [TypeScript](typescript.md#plugins).
