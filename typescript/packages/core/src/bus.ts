/**
 * The hook bus: runs the middleware for one hook event and combines their answers
 * (DESIGNS No. 8, fixtures suites `hook_order` and `bus`).
 *
 * 1. Middleware runs by band, baseline -> platform -> app -> task, and in registration
 *    order within a band; outbound hooks run innermost-first.
 * 2. Continue with `modified` hands the new payload to the next middleware.
 * 3. Block stops the chain: nothing outranks it.
 * 4. A middleware that throws or times out is handled by its fail mode: closed ->
 *    Block, open -> Continue (R2).
 * 5. The most severe outcome wins; every outcome is traced (R13).
 */

import type { Envelope } from "./envelope.js";
import { SpecError } from "./errors.js";
import { executionOrder, type Band, type EventOf, type HookEvent, type HookPoint } from "./hooks.js";
import { appliesTo, type Registration } from "./middleware.js";
import { mostSevere, type Outcome } from "./outcomes.js";
import type { RunTrace } from "./trace.js";

/** The combined outcome of one hook event, and the payload after every modification. */
export interface HookResult<E extends HookEvent = HookEvent> {
  hook: HookPoint;
  outcome: Outcome;
  event: E;
}

/** Whether the run can't go on: Block, Suspend or Escalate. */
export function halted(result: HookResult): boolean {
  return ["block", "suspend", "escalate"].includes(result.outcome.kind);
}

const KINDS = new Set(["continue", "retry", "escalate", "suspend", "block"]);

/** A middleware answered with something that isn't a valid outcome for this event. */
class BadAnswer extends TypeError {
  override name = "BadAnswer";
}

class TimedOut extends Error {
  override name = "TimeoutError";
}

function checked(answer: unknown, payload: HookEvent, name: string): Outcome {
  if (answer === undefined || answer === null) return { kind: "continue" };
  if (typeof answer !== "object" || !KINDS.has((answer as { kind?: string }).kind ?? "")) {
    throw new BadAnswer(`middleware ${name} returned ${typeof answer}, not an outcome`);
  }
  const outcome = answer as Outcome;
  if (outcome.kind === "continue" && outcome.modified !== undefined && outcome.modified !== null) {
    const hook = (outcome.modified as { hook?: unknown }).hook;
    if (hook !== payload.hook) throw new BadAnswer(`middleware ${name} modified the payload into another event type`);
  }
  return outcome;
}

function failureOutcome(registration: Registration, errorType: string, timedOut: boolean): Outcome {
  if (registration.failMode === "open") return { kind: "continue" };
  if (timedOut) return { kind: "block", reason: `middleware ${registration.name} timed out`, code: "middleware_timeout" };
  return { kind: "block", reason: `middleware ${registration.name} failed (${errorType})`, code: "middleware_error" };
}

async function call(registration: Registration, payload: HookEvent, env: Envelope): Promise<unknown> {
  const pending = Promise.resolve().then(() => registration.handler(payload, env));
  if (registration.timeout === undefined) return pending;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new TimedOut()), registration.timeout);
  });
  try {
    return await Promise.race([pending, deadline]);
  } finally {
    clearTimeout(timer);
  }
}

/** The middleware installed on one harness, and the algorithm that runs it (C4). */
export class HookBus {
  private readonly items: Registration[] = [];

  constructor(registrations: Iterable<Registration> = []) {
    for (const registration of registrations) this.add(registration);
  }

  /**
   * Install a middleware.
   *
   * @throws SpecError if a baseline-band middleware fails open (R2).
   */
  add(registration: Registration): void {
    if (registration.band === "baseline" && registration.failMode !== "closed") {
      throw new SpecError(
        `middleware ${registration.name} is in the baseline band but fails open; baseline middleware must fail closed (RULES R2)`,
        { name: registration.name },
      );
    }
    this.items.push(registration);
  }

  get registrations(): readonly Registration[] {
    return this.items;
  }

  /** The middleware that run for `hook`, in execution order. */
  chain(hook: HookPoint, task?: string | null): Registration[] {
    const applicable = this.items.filter((r) => appliesTo(r, hook, task));
    return executionOrder(applicable, hook, (r) => r.band);
  }

  /** Hook points that have middleware in `band` for `task`. */
  hooksInBand(band: Band, task?: string | null): Set<HookPoint> {
    const found = new Set<HookPoint>();
    for (const r of this.items) {
      if (r.band === band && (r.tasks === undefined || (task != null && r.tasks.has(task)))) for (const hook of r.hooks) found.add(hook);
    }
    return found;
  }

  /** Run every middleware for `hook` on `event` and combine the outcomes. */
  async emit<H extends HookPoint>(
    hook: H,
    event: EventOf<H>,
    env: Envelope,
    trace: RunTrace,
    options: { task?: string | null; source?: string } = {},
  ): Promise<HookResult<EventOf<H>>> {
    if (event.hook !== hook) throw new TypeError(`${hook} carries its own event type, not ${event.hook}`);
    let payload: HookEvent = event;
    const chain = this.chain(hook, options.task);
    const outcomes: Outcome[] = [];
    for (const registration of chain) {
      let result: Outcome;
      try {
        result = checked(await call(registration, payload, env), payload, registration.name);
        trace.outcome(hook, registration.name, registration.band, result);
      } catch (error) {
        const timedOut = error instanceof TimedOut;
        const errorType = timedOut ? "TimeoutError" : error instanceof Error ? error.name : typeof error;
        result = failureOutcome(registration, errorType, timedOut);
        // Only the error's type: its message may hold raw content (R9).
        trace.failure(hook, registration.name, registration.band, result, errorType, timedOut);
      }
      outcomes.push(result);
      if (result.kind === "continue" && result.modified !== undefined && result.modified !== null) payload = result.modified as HookEvent;
      if (result.kind === "block") break;
    }
    const combined = mostSevere(outcomes);
    trace.hook(hook, options.source ?? "harness", combined, chain.length);
    return { hook, outcome: combined, event: payload as EventOf<H> };
  }
}
