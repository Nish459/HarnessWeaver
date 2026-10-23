/**
 * Session style: the app owns the flow, the harness governs every step (DESIGNS No. 15).
 * `decide` fires `route.decide`, `guard` fires `input.before`, `context(...).check` fires
 * `context.after`, `validate` fires `output.before`, `tool` makes a governed call, and
 * `@harnessweaver/ai-sdk`'s `wrapModel` sends model calls through `generate`. A halting
 * outcome throws a `RunInterrupted` error in the app's code (ADR-0020).
 */

import type { ContextItem, Decision, ModelRequest, ModelResponse } from "./contracts.js";
import type { Envelope } from "./envelope.js";
import { SpecError, ValidationFailed } from "./errors.js";
import { newId } from "./ids.js";
import type { JsonObject, JsonValue } from "./json.js";
import type { ModelCall, RunContext } from "./runtime.js";
import type { RunTrace } from "./trace.js";

export interface DecideOptions {
  text?: string | null;
  options?: readonly string[];
  state?: JsonObject;
  /** The answer when no stage decides. */
  default?: string | null;
}

/** Governed access to one context source (`s.context("kb")`). */
export class ContextSource {
  constructor(
    private readonly run: RunContext,
    readonly source: string,
  ) {}

  /** Retrieve from the source's provider: ACLs re-checked, labelled, capped, then `context.after`. */
  fetch(query: string, options: { limit?: number } = {}): Promise<ContextItem[]> {
    return this.run.fetchContext(this.source, query, options.limit);
  }

  /** Govern items the app retrieved itself, then fire `context.after`. */
  check(items: readonly ContextItem[], options: { query?: string } = {}): Promise<ContextItem[]> {
    return this.run.contextAfter(this.source, items, options.query);
  }
}

/** Governed model, tool, routing and validation calls inside one run. */
export class Session {
  constructor(readonly run: RunContext) {}

  get envelope(): Envelope {
    return this.run.envelope;
  }

  get runId(): string {
    return this.run.runId;
  }

  get trace(): RunTrace {
    return this.run.trace;
  }

  /** Render a versioned prompt (ADR-0013). */
  async prompt(ref: string, variables: Readonly<Record<string, unknown>> = {}): Promise<string> {
    if (this.run.prompts === undefined) throw new SpecError("no prompts are configured");
    return this.run.prompts.render(ref, variables);
  }

  /** Ask the routing middleware to choose (`route.decide`). */
  decide(router: string, options: DecideOptions = {}): Promise<Decision> {
    return this.run.decide(
      { router, text: options.text ?? null, options: [...(options.options ?? [])], state: options.state ?? {} },
      options.default ?? null,
    );
  }

  /** Run the input guards on content the app received (`input.before`). */
  guard(stage: "input", content: JsonValue): Promise<JsonValue> {
    if (stage !== "input") throw new SpecError(`unknown guard stage '${String(stage)}'; use validate() for output`);
    return this.run.checkInput(content);
  }

  /** Governed access to a context source. */
  context(source: string): ContextSource {
    return new ContextSource(this.run, source);
  }

  /**
   * Check a final output (`output.before`); returns it, possibly modified.
   *
   * @throws ValidationFailed when a middleware asks for a repair (the app decides how).
   * @throws RunInterrupted when a hook halts the run.
   */
  async validate<T extends JsonValue>(stage: "output", value: T): Promise<T> {
    if (stage !== "output") throw new SpecError(`unknown validation stage '${String(stage)}'`);
    const result = await this.run.checkOutput(value);
    if (result.outcome.kind === "retry") throw new ValidationFailed(result.outcome.reason);
    this.run.output = result.event.output;
    return result.event.output as T;
  }

  /** Call a tool, governed (`tool.before`, the governor, `tool.after`); returns its output. */
  async tool(name: string, args: JsonObject = {}): Promise<JsonValue> {
    const result = await this.run.callTool({ id: newId("call"), name, arguments: args });
    return result.output ?? null;
  }

  /** One governed model call through the app's own model (for adapters such as wrapModel). */
  generate(request: ModelRequest, call: ModelCall): Promise<ModelResponse> {
    return this.run.generate(request, call);
  }
}
