/** A run's trace: every hook that fired, every middleware answer and failure, every note (R13). */

import { isoTime, type Clock } from "./clock.js";
import type { TraceEvent } from "./contracts.js";
import type { Band, HookPoint } from "./hooks.js";
import type { JsonObject } from "./json.js";
import type { Outcome, OutcomeKind } from "./outcomes.js";

function reasonOf(outcome: Outcome): string | null {
  return outcome.kind === "continue" ? (outcome.note ?? null) : outcome.reason;
}

function modified(outcome: Outcome): boolean {
  return outcome.kind === "continue" && outcome.modified !== undefined && outcome.modified !== null;
}

function codeOf(outcome: Outcome): string | null {
  return outcome.kind === "block" ? (outcome.code ?? "blocked") : null;
}

/** An append-only list of trace events for one run; `onEvent` sees each one as it lands. */
export class RunTrace implements Iterable<TraceEvent> {
  private readonly items: TraceEvent[];

  constructor(
    private readonly clock: Clock,
    events: readonly TraceEvent[] = [],
    private readonly onEvent?: (event: TraceEvent) => void,
  ) {
    this.items = [...events];
  }

  get events(): readonly TraceEvent[] {
    return this.items;
  }

  get length(): number {
    return this.items.length;
  }

  [Symbol.iterator](): Iterator<TraceEvent> {
    return [...this.items][Symbol.iterator]();
  }

  private append(fields: Omit<TraceEvent, "seq" | "at">): TraceEvent {
    const event: TraceEvent = { seq: this.items.length, at: isoTime(this.clock.now()), modified: false, details: {}, ...fields };
    this.items.push(event);
    this.onEvent?.(event);
    return event;
  }

  /** That `hook` fired, from `source`, and the combined outcome. */
  hook(hook: HookPoint, source: string, outcome: Outcome, middleware: number): TraceEvent {
    return this.append({
      kind: "hook", source, hook, band: null, outcome: outcome.kind, modified: modified(outcome),
      reason: reasonOf(outcome), code: codeOf(outcome), details: { middleware },
    });
  }

  /** A middleware's answer to a hook event. */
  outcome(hook: HookPoint, source: string, band: Band | null, outcome: Outcome): TraceEvent {
    return this.append({
      kind: "outcome", source, hook, band, outcome: outcome.kind, modified: modified(outcome),
      reason: reasonOf(outcome), code: codeOf(outcome),
    });
  }

  /** A middleware that threw or timed out, and what its fail mode chose. Only the error's type (R9). */
  failure(hook: HookPoint, source: string, band: Band | null, outcome: Outcome, errorType: string, timedOut: boolean): TraceEvent {
    return this.append({
      kind: "failure", source, hook, band, outcome: outcome.kind,
      reason: reasonOf(outcome), code: codeOf(outcome), details: { error_type: errorType, timed_out: timedOut },
    });
  }

  /** A framework event, such as a budget check, a decision or a status change. */
  note(
    source: string,
    reason: string,
    options: { hook?: HookPoint | null; code?: string | null; outcome?: OutcomeKind | null; details?: JsonObject } = {},
  ): TraceEvent {
    return this.append({
      kind: "note", source, hook: options.hook ?? null, band: null, outcome: options.outcome ?? null,
      reason, code: options.code ?? null, details: options.details ?? {},
    });
  }
}
