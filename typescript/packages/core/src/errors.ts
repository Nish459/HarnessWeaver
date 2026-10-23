/**
 * The error taxonomy, the same as Python's `harnessweaver.errors` (RULES C5).
 *
 * Every error has a stable `code` that is part of the wire contract (`ErrorInfo`),
 * so TypeScript, Python and the sidecar report failures the same way. Messages
 * never hold raw prompts, outputs or tool arguments (R9).
 */

import type { JsonValue } from "./json.js";

/** Stable, language-neutral error codes. */
export type ErrorCode =
  | "budget_exceeded"
  | "deadline_exceeded"
  | "policy_denied"
  | "validation_failed"
  | "provider_error"
  | "tool_error"
  | "expression_error"
  | "spec_invalid"
  | "not_found"
  | "blocked"
  | "escalated"
  | "suspended"
  | "internal";

/** The serializable form of an error (schema `error-info`). */
export interface ErrorInfo {
  code: ErrorCode;
  type: string;
  message: string;
  retryable: boolean;
  details: Record<string, JsonValue>;
}

/** Base class for every error HarnessWeaver raises across a public boundary. */
export class HarnessError extends Error {
  /** The stable code; subclasses set their own. */
  code: ErrorCode = "internal";
  /** Whether retrying may help. */
  retryable = false;
  /** Machine-readable facts about the failure, never raw content (R9). */
  readonly details: Record<string, JsonValue>;

  constructor(message: string, details: Record<string, JsonValue> = {}) {
    super(message);
    this.name = new.target.name;
    this.details = details;
  }

  /** The serializable form of this error. */
  toInfo(): ErrorInfo {
    return {
      code: this.code,
      type: this.name,
      message: this.message,
      retryable: this.retryable,
      details: this.details,
    };
  }
}

/** A run would exceed, or has exceeded, one of its budget limits. */
export class BudgetExceeded extends HarnessError {
  override code: ErrorCode = "budget_exceeded";
}

/** A run passed its deadline. */
export class DeadlineExceeded extends HarnessError {
  override code: ErrorCode = "deadline_exceeded";
}

/** A deterministic policy refused an action. */
export class PolicyDenied extends HarnessError {
  override code: ErrorCode = "policy_denied";
}

/** Input or output failed validation and could not be repaired. */
export class ValidationFailed extends HarnessError {
  override code: ErrorCode = "validation_failed";
}

/** A model or other upstream provider failed. Usually worth retrying. */
export class ProviderError extends HarnessError {
  override code: ErrorCode = "provider_error";
  override retryable = true;
}

/** A tool failed while executing. */
export class ToolError extends HarnessError {
  override code: ErrorCode = "tool_error";
}

/** A run, approval or other named thing doesn't exist. */
export class NotFound extends HarnessError {
  override code: ErrorCode = "not_found";
}

/** A hook stopped the run with Block, Escalate or Suspend (ADR-0020). */
export class RunInterrupted extends HarnessError {}

/** A hook refused the step; `details.code` holds the Block code. */
export class RunBlocked extends RunInterrupted {
  override code: ErrorCode = "blocked";
}

/** A hook handed the run to a human queue. */
export class RunEscalated extends RunInterrupted {
  override code: ErrorCode = "escalated";
}

/** A hook paused the run until an approver answers. */
export class RunSuspended extends RunInterrupted {
  override code: ErrorCode = "suspended";
}

/** A bug or an unexpected failure inside HarnessWeaver or a plugin. */
export class InternalError extends HarnessError {}

/** A cel-lite expression could not be compiled or evaluated. */
export class ExpressionError extends HarnessError {
  override code: ErrorCode = "expression_error";
}

/** A cel-lite expression is malformed or calls something that doesn't exist. */
export class ExpressionSyntaxError extends ExpressionError {}

/** A cel-lite expression failed at evaluation time (missing key, type mismatch, ...). */
export class ExpressionEvalError extends ExpressionError {}

/** A spec is invalid. Raised when a harness loads, never at run time. */
export class SpecError extends HarnessError {
  override code: ErrorCode = "spec_invalid";
}

/** A later layer changed a value the org baseline locked (R1). */
export class LockViolation extends SpecError {}

/** A value is outside the bounds the org baseline set (R10). */
export class BoundViolation extends SpecError {}

/** The app's effective spec is below the adoption level its risk tier requires. */
export class LevelTooLow extends SpecError {}

/** A runner or adapter can't reach a hook point the baseline needs (R4). */
export class UnreachableHook extends SpecError {}

/** A plugin was built for a contract range this core doesn't support (V5). */
export class IncompatibleContract extends SpecError {}

/** A spec names a provider or plugin that isn't registered (R4). */
export class UnknownProvider extends SpecError {}

/** Two plugins claim the same namespace. */
export class PluginConflict extends SpecError {}

/** A spec uses a plugin that the org baseline's `plugins.allow` list excludes. */
export class PluginNotAllowed extends SpecError {}

/** Translate any thrown value into the taxonomy, defaulting to `InternalError`. */
export function classify(error: unknown): HarnessError {
  if (error instanceof HarnessError) return error;
  const kind = error instanceof Error ? error.name : typeof error;
  if (kind === "TimeoutError" || kind === "AbortError") {
    return new DeadlineExceeded("the operation timed out");
  }
  return new InternalError(`unexpected ${kind}`);
}
