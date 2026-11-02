/**
 * The run context: one run's mutable state and every governed operation on it, the
 * same as Python's `RunContext` (DESIGNS No. 7, ADR-0020).
 *
 * Each operation fires its hook point on the bus and turns a halting outcome into a
 * taxonomy error: Block -> RunBlocked, Escalate -> RunEscalated. A TypeScript session
 * can't be resumed later, so a Suspend escalates instead (as a standalone Python
 * session does). Budgets are checked at `model.before`, `model.after` and `tool.before`.
 */

import { breachBlock, BudgetMeter, resolveCost, type Limit, type PriceLookup } from "./budgets.js";
import type { HookBus, HookResult } from "./bus.js";
import type { ContextSources } from "./context.js";
import type {
  ContextItem,
  Decision,
  DecisionRequest,
  Labels,
  ModelRequest,
  ModelResponse,
  StreamChunk,
  ToolCall,
  ToolResult,
} from "./contracts.js";
import type { RunScope } from "./current.js";
import { withLabels, type Envelope } from "./envelope.js";
import { DeadlineExceeded, ModelRefusal, RunBlocked, RunEscalated, SpecError, type RunInterrupted } from "./errors.js";
import type { EventOf, HookPoint } from "./hooks.js";
import type { JsonObject, JsonValue } from "./json.js";
import type { Outcome, Retry } from "./outcomes.js";
import type { PolicyEngine } from "./policy.js";
import type { PromptStore } from "./prompts.js";
import type { Governor } from "./tools/governor.js";
import type { ToolDescription } from "./tools/manifests.js";
import { RunTrace } from "./trace.js";

/** How many times a Retry at `model.after` may re-ask the model. */
export const MODEL_RETRIES = 1;

/** Finds and runs tools; the harness builds one from manifests and code handlers (S2). */
export interface ToolBackend {
  describe(name: string): ToolDescription | undefined;
  execute(call: ToolCall, env: Envelope): Promise<ToolResult>;
}

/** Sends a neutral request to the app's own model and answers neutrally (the AI SDK, say). */
export type ModelCall = (request: ModelRequest) => Promise<ModelResponse>;

/** What a run context is built from: the harness's parts for this run. */
export interface RunParts {
  bus: HookBus;
  envelope: Envelope;
  trace?: RunTrace;
  task?: string | null;
  input?: JsonValue;
  tools?: ToolBackend;
  governor?: Governor;
  policy?: PolicyEngine;
  context?: ContextSources;
  prompts?: PromptStore;
  prices?: PriceLookup;
  /** Model names the spec allows (`models.allowed_aliases` and their targets), if limited. */
  allowedModels?: ReadonlySet<string> | null;
}

function marked(labels: Labels, flag: "untrusted_seen" | "private_seen", source: string): Labels {
  const sources = labels.sources ?? [];
  return { ...labels, [flag]: true, sources: sources.includes(source) ? sources : [...sources, source] };
}

/** One run's state and governed operations. */
export class RunContext implements RunScope {
  envelope: Envelope;
  readonly trace: RunTrace;
  readonly meter: BudgetMeter;
  readonly contextIds = new Set<string>();
  readonly task: string | null;
  readonly input: JsonValue;
  /** The run's output so far, for `run.end` and evals. */
  output: JsonValue = null;

  constructor(private readonly parts: RunParts) {
    this.envelope = parts.envelope;
    this.trace = parts.trace ?? new RunTrace(parts.envelope.clock);
    this.meter = new BudgetMeter(parts.envelope.budget);
    this.task = parts.task ?? null;
    this.input = parts.input ?? null;
  }

  get runId(): string {
    return this.envelope.run_id;
  }

  get prompts(): PromptStore | undefined {
    return this.parts.prompts;
  }

  markUntrusted(source: string): void {
    this.envelope = withLabels(this.envelope, marked(this.envelope.labels, "untrusted_seen", source));
  }

  markPrivate(source: string): void {
    this.envelope = withLabels(this.envelope, marked(this.envelope.labels, "private_seen", source));
  }

  // --- hooks -------------------------------------------------------------------------------

  /**
   * Fire `hook` with the current envelope. Doesn't throw for outcomes.
   *
   * @throws DeadlineExceeded once the run is past its deadline.
   */
  async emit<H extends HookPoint>(hook: H, event: EventOf<H>, checkDeadline = true): Promise<HookResult<EventOf<H>>> {
    const deadline = this.envelope.deadline;
    if (checkDeadline && typeof deadline === "number" && this.envelope.clock.now() >= deadline) throw new DeadlineExceeded("the run passed its deadline");
    return this.parts.bus.emit(hook, event, this.envelope, this.trace, { task: this.task });
  }

  /** The error a halting outcome becomes (ADR-0020). */
  interrupt(hook: HookPoint, outcome: Outcome): RunInterrupted {
    let halt = outcome;
    if (halt.kind === "retry") halt = { kind: "block", reason: `Retry isn't supported at ${hook}: ${halt.reason}`, code: "retry_not_supported" };
    if (halt.kind === "suspend") {
      this.trace.note("harness", "can't suspend in a TypeScript session; escalating", { hook });
      halt = { kind: "escalate", reason: halt.reason, to: halt.approver_role ?? null };
    }
    if (halt.kind === "block") return new RunBlocked(halt.reason, { hook, code: halt.code ?? "blocked" });
    if (halt.kind === "escalate") return new RunEscalated(halt.reason, { hook, to: halt.to ?? null });
    throw new TypeError(`${halt.kind} doesn't halt a run`);
  }

  /** Throw the interrupt for a halting outcome; return for Continue (or Retry, when allowed). */
  haltOn(result: HookResult, allowRetry = false): void {
    const { outcome } = result;
    if (outcome.kind === "continue" || (allowRetry && outcome.kind === "retry")) return;
    throw this.interrupt(result.hook, outcome);
  }

  private budgetStop(hook: HookPoint, limit: Limit): never {
    const block = breachBlock(limit, this.meter.limits);
    this.trace.note("harness.budget", block.reason, { hook, code: block.code ?? null, outcome: "block" });
    throw new RunBlocked(block.reason, { hook, code: block.code ?? "budget_exceeded", limit });
  }

  // --- the run's steps ---------------------------------------------------------------------

  /**
   * Ask the policy engine whether this run may start (`run.start` rules, ADR-0025).
   *
   * @throws RunBlocked when a rule denies the run; RunEscalated when one asks for approval.
   */
  async authorizeRun(): Promise<void> {
    const policy = this.parts.policy;
    if (policy === undefined) return;
    const envelope = this.envelope;
    const decision = await policy.decide({
      hook: "run.start",
      principal: envelope.principal,
      tenant: envelope.tenant,
      task: envelope.task ?? null,
      task_version: envelope.task_version ?? null,
      labels: envelope.labels,
    });
    if ((decision.rule === null || decision.rule === undefined) && decision.effect === "allow") return;
    const reason = decision.reason || `the policy says ${decision.effect}`;
    const outcome = decision.effect === "deny" ? "block" : decision.effect === "require_approval" ? "escalate" : "continue";
    this.trace.note("harness.policy", reason, { hook: "run.start", outcome, details: { effect: decision.effect, rule: decision.rule ?? null } });
    if (decision.effect === "deny") throw new RunBlocked(reason, { hook: "run.start", code: "policy_denied" });
    if (decision.effect === "require_approval") throw new RunEscalated(reason, { hook: "run.start", code: "policy_requires_approval" });
  }

  /** Fire `input.before`; returns the (possibly redacted) input. */
  async checkInput(value: JsonValue): Promise<JsonValue> {
    const result = await this.emit("input.before", { hook: "input.before", input: value });
    this.haltOn(result);
    return result.event.input;
  }

  /** Fire `route.decide`; without an answer, use `fallback` or abstain. Traced (R13). */
  async decide(request: DecisionRequest, fallback?: string | null): Promise<Decision> {
    const result = await this.emit("route.decide", { hook: "route.decide", request, decision: null });
    this.haltOn(result);
    const decision: Decision = result.event.decision ?? (fallback != null
      ? { kind: "default", choice: fallback, confidence: null, reason: "no stage decided", stage: null }
      : { kind: "abstain", choice: null, confidence: null, reason: "no stage decided", stage: null });
    const details: JsonObject = { router: request.router, kind: decision.kind };
    if (decision.choice != null) details.choice = decision.choice;
    if (decision.confidence != null) details.confidence = decision.confidence;
    if (decision.stage != null) details.stage = decision.stage;
    this.trace.note("harness.decision", decision.reason || decision.kind, { hook: "route.decide", details });
    return decision;
  }

  /** Retrieve from a context source, governed. @throws SpecError for an unknown source. */
  async fetchContext(source: string, query: string, limit?: number | null): Promise<ContextItem[]> {
    if (this.parts.context === undefined) throw new SpecError("this run has no context sources");
    return this.contextAfter(source, await this.parts.context.fetch(this.envelope, source, query, limit), query);
  }

  /** Govern items (ACLs, labels, caps; ADR-0030), then fire `context.after`. Untrusted items label the run (S3). */
  async contextAfter(source: string, items: readonly ContextItem[], query?: string | null): Promise<ContextItem[]> {
    const governed = this.parts.context ? this.parts.context.govern(this.envelope, this.trace, source, items) : [...items];
    const result = await this.emit("context.after", { hook: "context.after", source, query: query ?? null, items: governed });
    this.haltOn(result);
    const kept = result.event.items;
    if (kept.some((item) => item.untrusted ?? true)) this.markUntrusted(`context:${source}`);
    for (const item of kept) this.contextIds.add(item.id);
    return kept;
  }

  /** Fire `output.before`; a Retry is returned for the caller to repair. */
  async checkOutput(output: JsonValue, attempt = 0, schemaName: string | null = null): Promise<HookResult<EventOf<"output.before">>> {
    const result = await this.emit("output.before", { hook: "output.before", output, attempt, schema_name: schemaName, approval: null });
    this.haltOn(result, true);
    return result;
  }

  /**
   * One governed tool call: the budget, `tool.before`, the governor (steps 1 to 7), the
   * tool, step 9 and `tool.after`. A tool that throws gives the model only its error's
   * type, since the message may hold content (R9).
   */
  async callTool(call: ToolCall): Promise<ToolResult> {
    const tools = this.parts.tools;
    const description = tools?.describe(call.name);
    if (tools === undefined || description === undefined) {
      const reason = `tool '${call.name}' isn't registered`;
      this.trace.note("harness.tools", reason, { hook: "tool.before", code: "tool_unknown" });
      throw new RunBlocked(reason, { hook: "tool.before", code: "tool_unknown" });
    }
    const limit = this.meter.checkToolCall();
    if (limit !== undefined) this.budgetStop("tool.before", limit);
    const before = await this.emit("tool.before", { hook: "tool.before", call, tool: description.info, approval: null });
    this.haltOn(before);
    const final = before.event.call;
    if (this.parts.governor) {
      const verdict = await this.parts.governor.authorize(this, final, description, null);
      if (verdict.decision === "block") throw new RunBlocked(verdict.reason, { hook: "tool.before", code: verdict.code ?? "blocked" });
      if (verdict.decision === "require_approval") throw this.interrupt("tool.before", { kind: "suspend", reason: verdict.reason, approver_role: verdict.approver_role ?? null });
    }
    this.meter.startToolCall();
    let result: ToolResult;
    try {
      result = await tools.execute(final, this.envelope);
    } catch (error) {
      const kind = error instanceof Error ? error.name : typeof error;
      this.trace.note("harness.tools", `tool ${final.name} raised ${kind}`, { hook: "tool.after", code: "tool_error" });
      result = { call_id: final.id, output: { error: kind }, is_error: true, untrusted: true, truncated: false };
    }
    if (this.parts.governor) result = await this.parts.governor.sanitize(this, final, description, result);
    const after = await this.emit("tool.after", { hook: "tool.after", call: final, tool: description.info, result });
    this.haltOn(after);
    const out = after.event.result;
    if (out.untrusted ?? true) this.markUntrusted(`tool:${final.name}`);
    if ((description.info.data_access ?? []).some((d) => d.startsWith("pii"))) this.markPrivate(`tool:${final.name}`);
    return out;
  }

  /** The clock the governor reads. */
  get clock() {
    return this.envelope.clock;
  }

  /**
   * The first half of a governed model call: the allowed models, the budget and
   * `model.before`, which may redact the request. Returns the request to send.
   *
   * @throws RunInterrupted when a hook or a budget halts the run.
   */
  async startModelCall(request: ModelRequest): Promise<ModelRequest> {
    const allowed = this.parts.allowedModels;
    const name = request.alias ?? request.model ?? null;
    if (allowed && (name === null || !allowed.has(name))) {
      const reason = `model ${name ?? "(unnamed)"} isn't one models.allowed_aliases allows`;
      this.trace.note("harness.models", reason, { hook: "model.before", code: "model_not_allowed" });
      throw new RunBlocked(reason, { hook: "model.before", code: "model_not_allowed" });
    }
    const limit = this.meter.checkModelCall(request);
    if (limit !== undefined) this.budgetStop("model.before", limit);
    const before = await this.emit("model.before", { hook: "model.before", request });
    this.haltOn(before);
    this.meter.startModelCall();
    return before.event.request;
  }

  /** Cost (ADR-0012) and usage against the budget, noted on the trace. Returns any limit passed. */
  private countModelCall(sent: ModelRequest, response: ModelResponse): Limit | undefined {
    const [cost, source] = resolveCost(response, sent, this.parts.prices);
    const over = this.meter.recordModelCall(response.usage ?? {}, cost);
    const usage: JsonObject = { input_tokens: response.usage?.input_tokens ?? 0, output_tokens: response.usage?.output_tokens ?? 0, cost_source: source };
    if (cost !== null) usage.cost_usd = cost;
    this.trace.note("harness.budget", "model usage", { hook: "model.after", details: usage });
    return over;
  }

  /**
   * Close a call the model declined: it still cost tokens, so it is counted, and the refusal
   * is noted on the trace (R13). `model.after` doesn't fire, as there is no answer to pass on.
   *
   * @returns `refusal`, for the caller to throw.
   */
  refuseModelCall(sent: ModelRequest, refusal: ModelRefusal): ModelRefusal {
    this.countModelCall(sent, refusal.response);
    this.trace.note("harness.models", refusal.message, { hook: "model.after", code: "model_refusal" });
    return refusal;
  }

  /**
   * The second half: cost (ADR-0012), usage against the budget, and `model.after`.
   * Returns the response as the middleware left it, and whether it asked for a retry.
   *
   * @throws RunInterrupted when a hook or a budget halts the run.
   */
  async finishModelCall(sent: ModelRequest, response: ModelResponse): Promise<[ModelResponse, Retry | undefined]> {
    const over = this.countModelCall(sent, response);
    const after = await this.emit("model.after", { hook: "model.after", request: sent, response });
    if (over !== undefined) this.budgetStop("model.after", over);
    if (after.outcome.kind === "retry") return [after.event.response, after.outcome];
    this.haltOn(after);
    return [after.event.response, undefined];
  }

  /**
   * One governed model call through `call` (the app's own model): `startModelCall`, the
   * call, `finishModelCall`. A Retry at `model.after` re-asks the model once.
   *
   * @throws RunInterrupted when a hook or a budget halts the run.
   */
  async generate(request: ModelRequest, call?: ModelCall): Promise<ModelResponse> {
    if (call === undefined) throw new SpecError("the TypeScript core has no model of its own; pass the call (wrapModel does)");
    for (let retries = 0; ; retries++) {
      const sent = await this.startModelCall(request);
      const answer = await call(sent).catch((error: unknown) => {
        throw error instanceof ModelRefusal ? this.refuseModelCall(sent, error) : error;
      });
      const [response, retry] = await this.finishModelCall(sent, answer);
      if (retry === undefined) return response;
      if (retries >= MODEL_RETRIES) throw this.interrupt("model.after", { kind: "block", reason: `model retries exhausted: ${retry.reason}`, code: "retry_exhausted" });
      this.trace.note("harness", `re-asking the model: ${retry.reason}`, { hook: "model.after" });
    }
  }

  /** Fire `stream.chunk` for one chunk of a streamed answer; returns it, possibly redacted. */
  async streamChunk(request: ModelRequest, chunk: StreamChunk, textSoFar: string): Promise<StreamChunk> {
    const result = await this.emit("stream.chunk", { hook: "stream.chunk", request, chunk, text_so_far: textSoFar });
    this.haltOn(result);
    return result.event.chunk;
  }
}
