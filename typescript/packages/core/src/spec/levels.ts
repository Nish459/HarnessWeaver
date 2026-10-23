/**
 * Adoption levels: what an effective spec reaches, and what its risk tier requires
 * (DESIGNS No. 11, fixtures suite `levels`). Levels are cumulative; each requirement has
 * a stable code that `harnessweaver doctor` reports too.
 */

import { isObject } from "../json.js";

export const LEVELS = ["L0", "L1", "L2", "L3", "L4"] as const;
export type Level = (typeof LEVELS)[number];

export const REQUIREMENTS: Record<string, string> = {
  "L1.enforcing_guardrail": "at least one enabled guardrail with mode: enforce",
  "L1.task_outputs": "every task declares an output",
  "L2.require_manifest": "tools.require_manifest is true",
  "L2.run_budget": "budgets.per_run sets at least one limit",
  "L2.policy_rules": "policy.rules has at least one rule",
  "L3.tasks": "at least one task is defined",
  "L4.task_evals": "every task has at least one eval suite",
};

export interface LevelReport {
  level: Level;
  required: Level;
  unmet: Partial<Record<Level, string[]>>;
}

export const rank = (level: Level): number => LEVELS.indexOf(level);

const STAGES = ["input", "context", "tool_result", "output", "stream"];
type Raw = { [key: string]: unknown };
const map = (value: unknown): Raw => (isObject(value) ? value : {});
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

function guardsOf(section: unknown): Raw[] {
  return STAGES.flatMap((stage) => list(map(section)[stage]).map(map));
}

/** Eval dataset files by task: every `evals` key but `online`. */
export function suitesOf(spec: Raw): Record<string, string[]> {
  return Object.fromEntries(Object.entries(map(spec.evals)).filter(([task]) => task !== "online")) as Record<string, string[]>;
}

/** Work out the level a validated spec reaches and the level its risk tier requires. */
export function assess(spec: Raw): LevelReport {
  const tasks = map(spec.tasks);
  const guards = [...guardsOf(spec.guardrails), ...Object.values(tasks).flatMap((t) => guardsOf(map(t).guardrails))];
  const budget = map(map(spec.budgets).per_run);
  const suites = suitesOf(spec);
  const checks: Record<Exclude<Level, "L0">, [string, boolean][]> = {
    L1: [
      ["L1.enforcing_guardrail", guards.some((g) => (g.enabled ?? true) === true && (g.mode ?? "enforce") === "enforce")],
      ["L1.task_outputs", Object.values(tasks).every((t) => Boolean(map(t).output))],
    ],
    L2: [
      ["L2.require_manifest", (map(spec.tools).require_manifest ?? true) === true],
      ["L2.run_budget", Object.values(budget).some((v) => v !== null && v !== undefined)],
      ["L2.policy_rules", list(map(spec.policy).rules).length > 0],
    ],
    L3: [["L3.tasks", Object.keys(tasks).length > 0]],
    L4: [["L4.task_evals", Object.keys(tasks).every((name) => list(suites[name]).length > 0)]],
  };
  const failures = Object.fromEntries(Object.entries(checks).map(([level, items]) => [level, items.filter(([, ok]) => !ok).map(([code]) => code)])) as Record<string, string[]>;
  let reached: Level = "L0";
  for (const level of ["L1", "L2", "L3", "L4"] as const) {
    if (failures[level]!.length) break;
    reached = level;
  }
  const unmet: Partial<Record<Level, string[]>> = {};
  for (const [level, codes] of Object.entries(failures)) if (rank(level as Level) > rank(reached) && codes.length) unmet[level as Level] = codes;
  const requireLevel = map(spec.require_level);
  const tier = String(map(spec.metadata).risk_tier ?? "internal");
  const required = (map(requireLevel.tiers)[tier] ?? requireLevel.default ?? "L0") as Level;
  return { level: reached, required, unmet };
}

/** Requirement codes still unmet for `level` and every level below it. */
export function missingFor(report: LevelReport, level: Level): string[] {
  return LEVELS.filter((l) => rank(l) <= rank(level)).flatMap((l) => report.unmet[l] ?? []);
}
