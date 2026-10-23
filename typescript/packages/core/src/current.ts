/**
 * The run in progress, for code that runs inside one without being handed it: guards
 * that mark the run private or read the context ids it kept, judges that make governed
 * model calls. Carried by AsyncLocalStorage, so concurrent runs never see each other.
 */

import { AsyncLocalStorage } from "node:async_hooks";
import type { ModelRequest, ModelResponse } from "./contracts.js";
import type { RunTrace } from "./trace.js";

/** What code inside a run may read from it or record on it. */
export interface RunScope {
  readonly trace: RunTrace;
  /** The context item ids the run kept (for `grounded.citations`). */
  readonly contextIds: ReadonlySet<string>;
  /** Private data entered the run (S3). */
  markPrivate(source: string): void;
  /** Untrusted content entered the run (S3). */
  markUntrusted(source: string): void;
  /** A governed, budgeted model call, for providers that ask a model (`llm.judge`). */
  generate?(request: ModelRequest): Promise<ModelResponse>;
}

const STORAGE = new AsyncLocalStorage<RunScope>();

/** The run in progress, or undefined outside one. */
export function currentRun(): RunScope | undefined {
  return STORAGE.getStore();
}

/** Run `fn` as part of `scope`. */
export function withRun<T>(scope: RunScope, fn: () => T): T {
  return STORAGE.run(scope, fn);
}
