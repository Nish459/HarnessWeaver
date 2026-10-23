/**
 * Middleware: functions attached to hook points (DESIGNS No. 8).
 *
 * `defineMiddleware` declares one; declaring activates nothing (S8). A middleware
 * returns an Outcome (or nothing for Continue) and never throws for control flow. If
 * it throws or times out anyway, its declared `fail_mode` decides (R2, ADR-0014).
 */

import { parseDuration } from "./durations.js";
import type { Envelope } from "./envelope.js";
import { isHookPoint, type Band, type HookEvent, type HookPoint } from "./hooks.js";
import { checkName } from "./plugins/names.js";
import type { Outcome } from "./outcomes.js";

export type FailMode = "closed" | "open";

/** An installed middleware: `async (event, envelope) => Outcome | undefined`. */
export type Handler = (event: HookEvent, env: Envelope) => Promise<Outcome | void | undefined> | Outcome | void | undefined;

/** A middleware installed on a harness's bus. */
export interface Registration {
  name: string;
  handler: Handler;
  hooks: ReadonlySet<HookPoint>;
  band: Band;
  failMode: FailMode;
  /** Milliseconds one call may take, or undefined for no limit. */
  timeout?: number;
  /** Only run for these tasks; undefined means every task and session. */
  tasks?: ReadonlySet<string>;
}

/** Whether a registration runs for `hook` in `task`. */
export function appliesTo(registration: Registration, hook: HookPoint, task: string | null | undefined): boolean {
  return registration.hooks.has(hook) && (registration.tasks === undefined || (task !== null && task !== undefined && registration.tasks.has(task)));
}

/** A declared middleware, as a plugin contributes it. */
export interface MiddlewareDef {
  readonly kind: "middleware";
  readonly name: string;
  readonly hooks: readonly HookPoint[];
  readonly band: Band;
  readonly failMode: FailMode;
  readonly timeout?: number;
  /** Build the handler from the spec's settings for it. */
  readonly build: (settings: Record<string, unknown>) => Handler;
}

export interface MiddlewareOptions {
  name: string;
  hooks: readonly string[];
  /** Required: what a throw or timeout turns into (ADR-0014). */
  fail_mode: FailMode;
  band?: Band;
  timeout?: string | number;
  /** The handler, or a builder that takes the spec's settings. */
  handler?: Handler;
  build?: (settings: Record<string, unknown>) => Handler;
}

/**
 * Declare a middleware.
 *
 * @throws RangeError for an unknown hook point, a missing fail mode, or a bad timeout.
 */
export function defineMiddleware(options: MiddlewareOptions): MiddlewareDef {
  checkName(options.name);
  const hooks: HookPoint[] = [];
  for (const hook of options.hooks) {
    if (!isHookPoint(hook)) throw new RangeError(`unknown hook point '${hook}'`);
    if (!hooks.includes(hook)) hooks.push(hook);
  }
  if (hooks.length === 0) throw new RangeError("a middleware must attach to at least one hook point");
  if (options.fail_mode !== "closed" && options.fail_mode !== "open") {
    throw new RangeError("fail_mode must be 'closed' or 'open' (ADR-0014)");
  }
  const timeout = options.timeout === undefined ? undefined : parseDuration(options.timeout);
  if (timeout !== undefined && timeout <= 0) throw new RangeError("a middleware timeout must be positive");
  const { handler, build } = options;
  if ((handler === undefined) === (build === undefined)) throw new RangeError("give a middleware either a handler or a build function");
  return {
    kind: "middleware",
    name: options.name,
    hooks,
    band: options.band ?? "app",
    failMode: options.fail_mode,
    ...(timeout === undefined ? {} : { timeout }),
    build: build ?? (() => handler as Handler),
  };
}
