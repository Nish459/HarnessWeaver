/**
 * The envelope: the immutable context every hook event carries (schema `envelope`).
 *
 * It records who a run acts for, what it does, how much it may spend and what data
 * it has touched. The clock rides along for decisions but is never serialized.
 */

import { SystemClock, isoTime, type Clock } from "./clock.js";
import type { Budget, Labels, Principal } from "./contracts.js";
import { formatDuration } from "./durations.js";
import { newId } from "./ids.js";
import type { JsonObject } from "./json.js";

export interface Envelope {
  readonly run_id: string;
  readonly parent_run_id?: string | null;
  readonly tenant: string;
  readonly principal: Principal;
  readonly task?: string | null;
  readonly task_version?: string | null;
  readonly budget: Budget;
  /** When the run must end, in milliseconds since the epoch. */
  readonly deadline?: number | null;
  readonly labels: Labels;
  readonly idempotency_key?: string | null;
  readonly trace_id?: string | null;
  readonly attributes: Record<string, string>;
  /** The clock decisions use. Not part of the serialized envelope. */
  readonly clock: Clock;
}

export interface EnvelopeOptions {
  tenant: string;
  principal: Principal | string;
  task?: string | null;
  task_version?: string | null;
  budget?: Budget;
  clock?: Clock;
  run_id?: string;
  parent_run_id?: string | null;
  idempotency_key?: string | null;
  trace_id?: string | null;
  attributes?: Record<string, string>;
}

/** A principal from its id or itself. */
export function principalOf(value: Principal | string): Principal {
  return typeof value === "string" ? { id: value, roles: [], attrs: {} } : { roles: [], attrs: {}, ...value };
}

/** The envelope for a new run; the deadline comes from `budget.deadline`. */
export function newEnvelope(options: EnvelopeOptions): Envelope {
  const clock = options.clock ?? new SystemClock();
  const budget = options.budget ?? {};
  return {
    run_id: options.run_id ?? newId("run"),
    parent_run_id: options.parent_run_id ?? null,
    tenant: options.tenant,
    principal: principalOf(options.principal),
    task: options.task ?? null,
    task_version: options.task_version ?? null,
    budget,
    deadline: budget.deadline !== null && budget.deadline !== undefined ? clock.now() + budget.deadline : null,
    labels: { data_class: null, untrusted_seen: false, private_seen: false, sources: [] },
    idempotency_key: options.idempotency_key ?? null,
    trace_id: options.trace_id ?? null,
    attributes: options.attributes ?? {},
    clock,
  };
}

/** A copy with new labels. */
export function withLabels(envelope: Envelope, labels: Labels): Envelope {
  return { ...envelope, labels };
}

/** The envelope as the contract writes it: no clock, durations and times as strings. */
export function envelopeJson(envelope: Envelope): JsonObject {
  const { clock: _clock, deadline, budget, ...rest } = envelope;
  const wireBudget: JsonObject = { ...(budget as JsonObject) };
  if (typeof budget.deadline === "number") wireBudget.deadline = formatDuration(budget.deadline);
  return { ...(rest as unknown as JsonObject), budget: wireBudget, deadline: typeof deadline === "number" ? isoTime(deadline) : null };
}
