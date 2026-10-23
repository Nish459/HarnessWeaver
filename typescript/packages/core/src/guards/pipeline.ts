/**
 * The guardrail pipeline (DESIGNS No. 20, fixtures suite `guards`).
 *
 * Each guard is one middleware on its stage's hook, so guards run in list order
 * (baseline first), redactions chain and the most severe action wins. Every string in
 * a structured payload is checked. Consecutive `parallel` guards run concurrently as
 * one group, their redactions applied in list order. At the context stage a block
 * drops the item, not the run. A shadow guard (`mode: log_only`) records what it would
 * do and changes nothing (R8). An approved output answers `require_approval`, and only
 * that (No. 18).
 */

import type { ApprovalDecision, GuardAction } from "../contracts.js";
import { currentRun } from "../current.js";
import type { Envelope } from "../envelope.js";
import type { ContextEvent, HookEvent, HookPoint } from "../hooks.js";
import type { JsonValue } from "../json.js";
import type { FailMode, Handler } from "../middleware.js";
import type { Outcome } from "../outcomes.js";
import type { Guardrail } from "./common.js";

export type Stage = "input" | "context" | "tool_result" | "output" | "stream";

export const STAGE_HOOKS: Record<Stage, HookPoint> = {
  input: "input.before",
  context: "context.after",
  tool_result: "tool.after",
  output: "output.before",
  stream: "stream.chunk",
};

export const ACTION_RANK: Record<GuardAction, number> = {
  allow: 0,
  log_only: 0,
  redact: 1,
  repair: 2,
  escalate: 3,
  require_approval: 4,
  block: 5,
};

/** One configured guard. */
export interface Guard {
  id: string;
  provider: Guardrail;
  /** Overrides the provider's action whenever it flags something. */
  action?: GuardAction | null;
  mode?: "enforce" | "log_only";
  failMode?: FailMode;
  /** Milliseconds, for a member of a parallel group. */
  timeout?: number | null;
  /** Its full name, like `guardrails.input[pii]`, as traces and reports use. */
  name?: string;
}

export function isShadow(guard: Guard): boolean {
  return guard.mode === "log_only" || guard.action === "log_only";
}

/** What one guard decided about a list of texts. */
export interface Verdict {
  action: GuardAction;
  texts: string[];
  reason?: string | null;
  findings: string[];
  /** Who approved the output, when an approval answered this guard's ask. */
  approvedBy?: string | null;
}

const passive = (action: GuardAction): boolean => action === "allow" || action === "log_only";

/** Run a guard over every text and combine its answers: the most severe wins. */
export async function check(guard: Guard, texts: readonly string[], env: Envelope, approval?: ApprovalDecision | null): Promise<Verdict> {
  if (isShadow(guard) || approval?.decision === "reject") approval = null;
  let worst: GuardAction = "allow";
  const out = [...texts];
  let reason: string | null = null;
  const found = new Set<string>();
  let approvedBy: string | null = null;
  for (const [index, text] of texts.entries()) {
    const result = await guard.provider.check(text, env);
    const findings = result.findings ?? [];
    // A fact about the run, whatever the guard does about it: drives the trifecta (S3).
    if (findings.some((f) => f.private)) currentRun()?.markPrivate(`guard:${guard.id}`);
    let action = result.action;
    if (passive(action)) continue;
    if (guard.action && guard.action !== "log_only") action = guard.action;
    for (const finding of findings) found.add(finding.type);
    if (action === "require_approval" && approval) {
      // The human answered this ask; the guard's other answers still stand.
      approvedBy = approval.approver.id;
      continue;
    }
    if (action === "redact") {
      if (result.content === null || result.content === undefined) {
        action = "block";
        reason ??= `${result.reason ?? "flagged"} (it can't be redacted)`;
      } else {
        out[index] = result.content;
      }
    }
    reason ??= result.reason ?? null;
    if (ACTION_RANK[action] > ACTION_RANK[worst]) worst = action;
  }
  const verdict: Verdict = { action: worst, texts: out, reason, findings: [...found].sort(), approvedBy };
  note(guard, verdict);
  return verdict;
}

/** Trace a guard that fired, would have in shadow mode, or was answered by an approval (R8, R13). */
function note(guard: Guard, verdict: Verdict): void {
  const run = currentRun();
  if (run === undefined) return;
  const name = guard.name || guard.id;
  if (verdict.approvedBy) {
    run.trace.note("harness.guard", `${name} require_approval approved by ${verdict.approvedBy}`, {
      code: "guard_approved",
      details: { guard: name, action: "require_approval", approved_by: verdict.approvedBy, findings: verdict.findings },
    });
  }
  if (passive(verdict.action)) return;
  const shadow = isShadow(guard);
  run.trace.note("harness.guard", `${name} ${shadow ? "would " : ""}${verdict.action}`, {
    code: shadow ? "guard_shadow" : "guard_fired",
    details: { guard: name, action: verdict.action, findings: verdict.findings },
  });
}

export function outcomeOf(label: string, verdict: Verdict, stage: Stage, rebuilt: HookEvent | null): Outcome {
  const reason = `${label}: ${verdict.reason || verdict.action}`;
  const approved = verdict.approvedBy ? `approved by ${verdict.approvedBy}` : null;
  switch (verdict.action) {
    case "allow":
    case "log_only":
      return { kind: "continue", note: approved ? `${label}: ${approved}` : null };
    case "redact":
      return { kind: "continue", modified: rebuilt, note: approved ? `${reason}; ${approved}` : reason };
    case "repair":
      return stage === "output" ? { kind: "retry", reason } : { kind: "block", reason, code: "guard_blocked" };
    case "escalate":
      return { kind: "escalate", reason };
    case "require_approval":
      return { kind: "suspend", reason };
    default:
      return { kind: "block", reason, code: "guard_blocked" };
  }
}

export function shadowOutcome(label: string, verdict: Verdict): Outcome {
  if (passive(verdict.action)) return { kind: "continue" };
  return { kind: "continue", note: `would ${verdict.action}: ${label}: ${verdict.reason ?? ""}`.replace(/[: ]+$/, "") };
}

// --- reading the strings a stage checks, and putting them back -------------------------

type Path = (string | number)[];

function leaves(value: JsonValue | undefined, path: Path = []): [Path, string][] {
  if (typeof value === "string") return [[path, value]];
  if (Array.isArray(value)) return value.flatMap((item, i) => leaves(item, [...path, i]));
  if (value !== null && typeof value === "object") return Object.entries(value).flatMap(([key, item]) => leaves(item, [...path, key]));
  return [];
}

function replaced(value: JsonValue | undefined, changes: Map<string, string>, path: Path = []): JsonValue | undefined {
  const key = JSON.stringify(path);
  if (changes.has(key)) return changes.get(key);
  if (Array.isArray(value)) return value.map((item, i) => replaced(item, changes, [...path, i]) as JsonValue);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, item]) => [k, replaced(item, changes, [...path, k]) as JsonValue]));
  }
  return value;
}

/** The texts a stage checks, and how to rebuild the event from redacted ones. */
export function contentOf(stage: Stage, event: HookEvent): [string[], (texts: readonly string[]) => HookEvent] {
  if (event.hook === "stream.chunk") {
    return [[event.chunk.delta ?? ""], (texts) => ({ ...event, chunk: { ...event.chunk, delta: texts[0] ?? "" } })];
  }
  let root: JsonValue | undefined;
  let wrap: (value: JsonValue | undefined) => HookEvent;
  if (event.hook === "tool.after") {
    root = event.result.output;
    wrap = (value) => ({ ...event, result: { ...event.result, output: value ?? null } });
  } else if (event.hook === "input.before") {
    root = event.input;
    wrap = (value) => ({ ...event, input: value ?? null });
  } else if (event.hook === "output.before") {
    root = event.output;
    wrap = (value) => ({ ...event, output: value ?? null });
  } else {
    throw new TypeError(`stage ${stage} doesn't read ${event.hook}`);
  }
  const found = leaves(root);
  return [
    found.map(([, text]) => text),
    (texts) => wrap(replaced(root, new Map(found.map(([path], i) => [JSON.stringify(path), texts[i] ?? ""])))),
  ];
}

// --- the middleware -------------------------------------------------------------------

/** A parallel group member, with its own timeout and fail mode. */
async function member(guard: Guard, texts: readonly string[], env: Envelope, approval: ApprovalDecision | null): Promise<Verdict> {
  try {
    const pending = check(guard, texts, env, approval);
    if (!guard.timeout) return await pending;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const late = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(Object.assign(new Error("timed out"), { name: "TimeoutError" })), guard.timeout ?? 0);
    });
    try {
      return await Promise.race([pending, late]);
    } finally {
      clearTimeout(timer);
    }
  } catch (error) {
    const reason = `guard failed (${error instanceof Error ? error.name : typeof error})`;
    currentRun()?.trace.note(`guard:${guard.id}`, reason, { code: "guard_error" });
    if (guard.failMode === "open") return { action: "allow", texts: [...texts], findings: [] };
    return { action: "block", texts: [...texts], reason, findings: [] };
  }
}

async function group(guards: readonly Guard[], texts: readonly string[], env: Envelope, approval: ApprovalDecision | null): Promise<[Verdict, string[]]> {
  const verdicts = await Promise.all(guards.map((g) => member(g, texts, env, approval)));
  const notes = guards.flatMap((g, i) => (isShadow(g) && !passive(verdicts[i]!.action) ? [`would ${verdicts[i]!.action}: ${g.id}`] : []));
  notes.push(...guards.flatMap((g, i) => (verdicts[i]!.approvedBy ? [`${g.id}: approved by ${verdicts[i]!.approvedBy}`] : [])));
  const enforced = guards.map((g, i) => [g, verdicts[i]!] as const).filter(([g]) => !isShadow(g));
  let worst: Verdict = { action: "allow", texts: [...texts], findings: [] };
  for (const [, verdict] of enforced) if (ACTION_RANK[verdict.action] > ACTION_RANK[worst.action]) worst = verdict;
  if (worst.action === "redact") {
    // Redactions chain in list order: each redacting guard runs again on the text so far.
    let current = [...texts];
    for (const [guard, verdict] of enforced) {
      if (verdict.action === "redact") {
        const again = await member(guard, current, env, approval);
        if (again.action === "redact") current = again.texts;
      }
    }
    worst = { ...worst, texts: current };
  }
  return [worst, notes];
}

async function contextStage(event: ContextEvent, env: Envelope, guards: readonly Guard[], label: string): Promise<Outcome> {
  const kept = [];
  let dropped = 0;
  let changed = false;
  const notes: string[] = [];
  for (const item of event.items) {
    let content = item.content;
    let drop = false;
    for (const guard of guards) {
      const verdict = await check(guard, [content], env);
      if (passive(verdict.action)) continue;
      if (isShadow(guard)) {
        notes.push(`would ${verdict.action}: ${guard.id}`);
        continue;
      }
      if (verdict.action === "redact") content = verdict.texts[0] ?? content;
      else if (verdict.action === "block" || verdict.action === "repair") {
        drop = true;
        break;
      } else {
        return outcomeOf(label, verdict, "context", null);
      }
    }
    if (drop) {
      dropped += 1;
      continue;
    }
    if (content !== item.content) {
      changed = true;
      kept.push({ ...item, content });
    } else {
      kept.push(item);
    }
  }
  if (dropped) notes.push(`dropped ${dropped} item(s)`);
  const note = notes.join("; ") || null;
  return dropped || changed ? { kind: "continue", modified: { ...event, items: kept }, note } : { kind: "continue", note };
}

/** The middleware for one guard, or one parallel group of guards. */
export function guardHandler(stage: Stage, guards: readonly Guard[], label: string): Handler {
  if (guards.length === 0) throw new RangeError("a guard handler needs at least one guard");
  return async (event, env) => {
    if (stage === "context") return contextStage(event as ContextEvent, env, guards, label);
    const [texts, rebuild] = contentOf(stage, event);
    if (texts.length === 0) return undefined;
    // Only an output carries a human's approval to the guards (No. 18).
    const approval = event.hook === "output.before" ? (event.approval ?? null) : null;
    const [only] = guards;
    if (guards.length === 1 && only !== undefined) {
      const verdict = await check(only, texts, env, approval);
      return isShadow(only) ? shadowOutcome(label, verdict) : outcomeOf(label, verdict, stage, rebuild(verdict.texts));
    }
    const [verdict, notes] = await group(guards, texts, env, approval);
    const outcome = outcomeOf(label, verdict, stage, rebuild(verdict.texts));
    if (notes.length && outcome.kind === "continue") return { kind: "continue", modified: outcome.modified, note: notes.join("; ") };
    return outcome;
  };
}
