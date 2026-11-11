# Modules

Every capability in HarnessWeaver is a **module**: a port (a typed interface), a default provider, the middleware it installs on hook points, and its section of the spec. Apps pick modules by writing their sections; modules pick providers with `use:`. Swapping a provider never changes the hook points, the trace or the rest of the spec.

| Module | Spec section | Port(s) | Built-in and first-party providers | Planned | Hook points |
| --- | --- | --- | --- | --- | --- |
| [Models](../tutorial/models.md) | `models` | `ModelProvider` | `scripted`; plugins: `openai.chat`, `anthropic.messages` | Bedrock and Vertex through LiteLLM | `model.*`, `stream.chunk` |
| [Routing](../tutorial/routing.md) | `routing` | `Decider`, `Embedder` | `rules`, `lexical`, `semantic` (with `semantic.hashing`), `llm`, any `@hw.decider` | semantic-router, RouteLLM | `route.decide` |
| [Context and memory](../tutorial/context.md) | `context`, `memory` | `ContextProvider`, `Memory` | `memory`, `passthrough`; in-process memory store | pgvector, OpenSearch, Qdrant | `context.after` |
| [Guardrails](../tutorial/guardrails.md) | `guardrails` | `Guardrail` | `pii.regex`, `secrets.scan`, `injection.heuristic`, `regex.deny`, `size.limit`, `topic.deny`, `grounded.citations`, `llm.judge` | Presidio, Llama Guard, Prompt Guard | `input.before`, `context.after`, `tool.after`, `output.before`, `stream.chunk` |
| [Validation](../tutorial/validation.md) | `validation`, `tasks.*.output` | - | Pydantic parsing with bounded repair, cel-lite business rules | groundedness scorers | `output.before` |
| [Tools](../tutorial/tools.md) | `tools`, manifests | `ToolBackend`, `ToolGovernor`, `Sandbox` | Manifest registry, the nine-step governor, `native`, `http` and `code` transports; plugin: `monty.sandbox` | MCP transport | `tool.before`, `tool.after` |
| [Policy](../tutorial/policy.md) | `policy` | `PolicyEngine` | `cel_lite`; plugin: `cel.policy` | Cedar, OPA, OpenFGA | `tool.before`, `run.start` |
| [Approvals](../tutorial/approvals.md) | `approvals`, `tasks.*.approvals` | `ApprovalChannel` | `memory`, `callback`, `console`, `webhook`, `email` | Slack, an approval page | `tool.before`, `output.before`, `approval.resolved` |
| [State and replay](../tutorial/state.md) | `state` | `StateStore` | `memory`, `sqlite` | Postgres, Redis | `run.*`, `approval.resolved` |
| [Observability](../tutorial/observability.md) | `observability` | `Telemetry` | OpenTelemetry API spans and metrics, the in-memory `RunTrace`; plugin: `otel.sdk` | Langfuse, Phoenix, Logfire exporters | all |
| [Evals](../tutorial/evals.md) | `evals` | `Evaluator` | `exact`, `field_equals`, `numeric_close`, `contains`, `regex`, `schema_valid`, `citation_present`, `guard_fired`, `status`, `llm_judge` | promptfoo, DeepEval, Ragas | `run.end` |

Two more pieces are part of the core rather than modules: **budgets** ([Envelope, labels and budgets](../concepts/envelope.md#budgets)) and **prompts** ([section reference](spec.md#prompts)).

## Providers and determinism

Every provider declares whether it is **deterministic** (the same input always gives the same answer). This matters for trust: probabilistic components, such as LLM judges and semantic routers, may route a decision or *tighten* it (raise it to approval or block), but they never grant anything. A `PolicyEngine` must be deterministic (RULES R3).

| Deterministic | Probabilistic |
| --- | --- |
| `pii.regex`, `secrets.scan`, `injection.heuristic`, `regex.deny`, `size.limit`, `topic.deny`, `grounded.citations`, `cel_lite`, `rules`, `lexical`, `semantic` (with the hashing embedder), the deterministic graders | `llm.judge`, the `llm` routing stage, the `llm_judge` grader |

## Writing your own

Any module's port can be implemented by a plugin, in your own repository, and selected with `use: <namespace>.<name>`. See [Providers and ports](../advanced/providers.md).
