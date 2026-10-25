# ADR-0037: One adapter object per agent framework

**Status:** Accepted

## Decision

Agent frameworks are governed through one adapter object per framework that sends each of the framework's model requests through `RunContext.generate(provider=...)` and each tool call through `RunContext.call_tool(backend=...)`, rather than through one framework hook per hook point. For Pydantic AI that is `HarnessCapability`: `wrap_run` opens a run when none is active, `before_model_request` wraps the model, `wrap_tool_execute` governs each call, `after_output_process` fires `output.before` (a repair request becomes `ModelRetry`) and `handle_deferred_tool_calls` brings `requires_approval` tools to the harness's approvers. The `pydantic_ai.agent` runner adds `DeferredToolRequests` to the agent's output types, suspends on a deferred call and resumes with `DeferredToolResults`; a wrapped agent escalates instead. During a replay the recording answers an adapter's own model and tool calls (`RunContext.replaying`). The plugin requires `pydantic-ai-slim>=2.57,<3`.

## Why

Budgets, cost, telemetry, recording and the governor already live in the governed calls, and a framework's separate before and after hooks can't give them one place to run; Pydantic AI's deferred tools are its own way to pause a run, so a resumed run is the framework's own resume, not a copy of it; the harness, not the framework, decides which call a human approved (R3); a replay must never run an app's tool (ADR-0035).
