# History, design and future

## History

HarnessWeaver started from a design guide, the *AI Harness Framework Design and Build Guide*, which set out what an AI harness must do and how a framework for building them could work. The guide is kept unchanged in the repository ([on GitHub](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/AI%20Harness%20Framework%20Design%20and%20Build%20Guide.md)). Where the implementation departs from it, an architecture decision record says why, and [DESIGNS.md No. 29](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/DESIGNS.md#29-deviations-from-the-design-guide) lists every deviation.

## Design

The architecture is in [DESIGNS.md](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/DESIGNS.md): the hook bus, spec layering, the modules, the governor, approvals and cross-language delivery. Every feature is tested against the [design goals](../concepts/index.md#design-goals), in order, and when two conflict, the earlier one wins. Safety comes first: org baseline controls apply automatically and can't be switched off by app config.

The invariants that protect the framework's promises to the teams that adopt it are numbered in [RULES.md](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/RULES.md), so reviews and code can cite them:

| Rule | Promise |
| --- | --- |
| R1 | Baseline controls can't be removed |
| R2 | The baseline fails closed |
| R3 | Probabilistic components never grant |
| R4 | No silent gaps: unknown keys and unreachable hooks fail loading |
| R5 | One owner per control |
| R6 | A small core |
| R7 | Contracts don't leak frameworks |
| R8 | New guards start in shadow mode |
| R9 | No raw content before redaction |
| R10 | Bounds are errors, not clamps |
| R11 | Contracts first, in every language |
| R12 | Govern, don't compete: no agent loop in the core |
| R13 | Every decision is observable |
| R14 | Everything runs offline |

Every decision with a reason a future contributor would otherwise have to rediscover is an architecture decision record, indexed in [DESIGNS.md No. 28](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/DESIGNS.md#28-architecture-decision-records).

## Future

These are planned, and marked *planned* where the docs mention them:

- **Models:** Bedrock and Vertex through LiteLLM. Streaming through an instrumented client or a wrapped agent.
- **Guards:** Presidio, Llama Guard and Prompt Guard providers.
- **Routing:** semantic-router and RouteLLM stages. The `semantic` and `llm` stages in TypeScript.
- **Retrieval:** pgvector, OpenSearch and Qdrant context sources.
- **Tools:** the MCP transport. The `http`, `code` and `mcp` transports in TypeScript.
- **Policy:** Cedar, OPA and OpenFGA engines.
- **Approvals:** Slack and an approval page.
- **State:** Postgres and Redis stores, and durable runners on Temporal or DBOS.
- **Observability:** Langfuse, Phoenix and Logfire exporters, and OpenTelemetry export from TypeScript.
- **Evals:** promptfoo, DeepEval and Ragas adapters.
- **Cost:** prices from the `genai-prices` package, when it's installed.
