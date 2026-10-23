/**
 * What a middleware returns, and how several answers to one event combine (DESIGNS
 * No. 8, fixtures suite `outcomes`).
 *
 * Severity, most to least: Block > Suspend > Escalate > Retry > Continue(modified) >
 * Continue. The most severe outcome wins; the earliest one wins a tie.
 */

export interface Continue {
  kind: "continue";
  /** The replacement event payload, if any. */
  modified?: unknown;
  note?: string | null;
}

export interface Retry {
  kind: "retry";
  reason: string;
}

export interface Escalate {
  kind: "escalate";
  reason: string;
  to?: string | null;
}

export interface Suspend {
  kind: "suspend";
  reason: string;
  approver_role?: string | null;
}

export interface Block {
  kind: "block";
  reason: string;
  code?: string;
}

export type Outcome = Continue | Retry | Escalate | Suspend | Block;
export type OutcomeKind = Outcome["kind"];

const SEVERITY: Record<OutcomeKind, number> = { continue: 0, retry: 2, escalate: 3, suspend: 4, block: 5 };

/** Rank an outcome: Continue 0, Continue(modified) 1, ... Block 5. */
export function severity(outcome: Outcome): number {
  if (outcome.kind === "continue") return outcome.modified === undefined || outcome.modified === null ? 0 : 1;
  return SEVERITY[outcome.kind];
}

/** The most severe outcome; an empty list means nobody objected, so `Continue`. */
export function mostSevere(outcomes: Iterable<Outcome>): Outcome {
  let best: Outcome = { kind: "continue" };
  let bestRank = -1;
  for (const outcome of outcomes) {
    const rank = severity(outcome);
    if (rank > bestRank) {
      best = outcome;
      bestRank = rank;
    }
  }
  return best;
}

/** Shorthands for building outcomes. */
export const outcome = {
  continue: (modified?: unknown): Continue => (modified === undefined ? { kind: "continue" } : { kind: "continue", modified }),
  retry: (reason: string): Retry => ({ kind: "retry", reason }),
  escalate: (reason: string, to?: string): Escalate => ({ kind: "escalate", reason, ...(to ? { to } : {}) }),
  suspend: (reason: string, approverRole?: string | null): Suspend => ({ kind: "suspend", reason, approver_role: approverRole ?? null }),
  block: (reason: string, code = "blocked"): Block => ({ kind: "block", reason, code }),
};
