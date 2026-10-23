/**
 * Evals (DESIGNS No. 23, ADR-0033, ADR-0034, fixtures suite `evals`): datasets and
 * grader labels, the deterministic graders, suite summaries, baseline comparisons,
 * online sampling and the shadow-guard report.
 *
 * A grader is written as its name, or `{name: settings}`, where a single setting fills
 * the field the grader names as its shorthand (`{field_equals: total}`). Graders are
 * labelled `name`, `name:value`, or `name#n` for a list or map setting. Reasons name
 * fields, texts by position and rules, never the output's content (R9).
 */

import type { GuardAction, RunStatus } from "./contracts.js";
import { canonicalJson, canonicalUnicode } from "./digests.js";
import { SpecError, UnknownProvider } from "./errors.js";
import { SCHEMAS } from "./generated/contracts.js";
import { isObject, type JsonValue } from "./json.js";
import { checkSchema, SchemaError, validate, withDefaults, type Schema } from "./jsonschema.js";
import { fnv1a32 } from "./text.js";

// --- datasets and labels -------------------------------------------------------------------

export type GraderItem = string | { [name: string]: JsonValue };

export interface GraderSpec {
  use: string;
  settings: JsonValue;
  label: string;
}

function scalarText(value: JsonValue): string {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return value;
  return canonicalJson(value);
}

/**
 * Read graders as written and label them.
 *
 * @throws RangeError for a map without exactly one name, or a label used twice.
 */
export function parseGraders(items: readonly GraderItem[]): GraderSpec[] {
  const found: GraderSpec[] = [];
  const uses = new Map<string, number>();
  for (const item of items) {
    let use: string;
    let settings: JsonValue;
    if (typeof item === "string") {
      use = item;
      settings = null;
    } else if (isObject(item) && Object.keys(item).length === 1) {
      [[use, settings]] = Object.entries(item) as [[string, JsonValue]];
    } else {
      throw new RangeError("a grader is a name, or a map with exactly one name");
    }
    if (!use) throw new RangeError("a grader needs a name");
    uses.set(use, (uses.get(use) ?? 0) + 1);
    const label =
      settings === null || settings === undefined
        ? use
        : Array.isArray(settings) || isObject(settings)
          ? `${use}#${uses.get(use)}`
          : `${use}:${scalarText(settings)}`;
    if (found.some((g) => g.label === label)) throw new RangeError(`grader ${label} is listed twice`);
    found.push({ use, settings: settings ?? null, label });
  }
  return found;
}

export interface EvalCase {
  id: string;
  description?: string | null;
  input?: JsonValue;
  expect?: JsonValue;
  graders: GraderItem[];
  principal: string;
  tenant: string;
  tags: string[];
}

export interface EvalDataset {
  suite: string;
  task: string;
  description?: string | null;
  graders: GraderItem[];
  thresholds: { pass_rate: number };
  cases: EvalCase[];
}

/** The suite's graders followed by the case's own, labelled. */
export function gradersFor(dataset: EvalDataset, item: EvalCase): GraderSpec[] {
  return parseGraders([...dataset.graders, ...item.graders]);
}

/**
 * Validate a dataset document: the `eval-dataset` schema, unique case ids, and graders
 * every case can be graded by.
 *
 * @throws SpecError naming `source` and the problems.
 */
export function readDataset(document: unknown, source: string): EvalDataset {
  const schema = SCHEMAS["eval-dataset"] as Schema;
  const problems = validate(document, schema);
  if (problems.length) throw new SpecError(`${source}: ${problems.join("; ")}`);
  const dataset = withDefaults(document, schema) as EvalDataset;
  const seen = new Set<string>();
  for (const item of dataset.cases) {
    if (seen.has(item.id)) throw new SpecError(`${source}: case ${item.id} is listed twice`);
    seen.add(item.id);
    let graders: GraderSpec[];
    try {
      graders = gradersFor(dataset, item);
    } catch (error) {
      throw new SpecError(`${source}: ${(error as Error).message}`);
    }
    if (graders.length === 0) throw new SpecError(`${source}: case ${item.id} has no graders`);
  }
  return dataset;
}

// --- reading values -------------------------------------------------------------------------

/** What `valueAt` returns for a path that leads nowhere. */
export const MISSING: unique symbol = Symbol("MISSING");

/** JSON equality: numbers by value, never a boolean as a number, maps in any key order. */
export function jsonEqual(a: unknown, b: unknown): boolean {
  if (typeof a === "number" && typeof b === "number") return a === b;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => jsonEqual(x, b[i]));
  if (isObject(a) && isObject(b)) {
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every((k) => k in b && jsonEqual(a[k], b[k]));
  }
  return a === b;
}

/** Follow a dotted path (`line_items.1.amount`): map keys, and list indexes from 0. */
export function valueAt(value: unknown, path: string): unknown {
  let current = value;
  for (const part of path.split(".")) {
    if (isObject(current) && part in current) current = current[part];
    else if (Array.isArray(current) && /^\d+$/.test(part) && Number(part) < current.length) current = current[Number(part)];
    else return MISSING;
  }
  return current;
}

/**
 * The text graders search: a string as it is, nothing for null, and anything else as
 * canonical JSON with non-ASCII kept.
 */
export function outputText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  return canonicalUnicode(value);
}

// --- graders --------------------------------------------------------------------------------

export interface GuardFiring {
  guard: string;
  action: GuardAction;
  shadow?: boolean;
}

/** What a grader sees: one run's outcome, and the case it ran for. */
export interface EvalSample {
  case?: string | null;
  task?: string | null;
  input?: JsonValue;
  expect?: JsonValue;
  output?: JsonValue;
  status?: RunStatus;
  error_code?: string | null;
  guards?: GuardFiring[];
  output_schema?: Schema | null;
}

export interface Grade {
  passed: boolean;
  score: number;
  reason: string | null;
}

/** The port every grader implements; graders only measure, never grant (R3). */
export interface Evaluator {
  grade(sample: EvalSample): Promise<Grade> | Grade;
}

const of = (passed: boolean, reason: string | null = null): Grade => ({ passed, score: passed ? 1 : 0, reason });
const texts = (value: unknown): string[] => (typeof value === "string" ? [value] : (value as string[]));

/** Whether a guard's full name is `wanted`, or ends with `[wanted]`. */
export function guardMatches(name: string, wanted: string): boolean {
  return name === wanted || name.endsWith(`[${wanted}]`);
}

interface GraderDef {
  /** The field a single setting fills, or undefined when the grader takes no setting. */
  shorthand?: string;
  /** The settings schema. */
  settings: Schema;
  deterministic: boolean;
  create(settings: Record<string, unknown>): Evaluator;
}

const STRINGS = { anyOf: [{ type: "string", minLength: 1 }, { type: "array", minItems: 1, items: { type: "string", minLength: 1 } }] };
const STATUSES = ["pending", "running", "awaiting_approval", "completed", "blocked", "escalated", "failed", "cancelled"];
const CITATION_PATTERN = "\\[([A-Za-z0-9_.:#/-]+)\\]";

function object(properties: Record<string, unknown>, required: string[] = []): Schema {
  return { type: "object", additionalProperties: false, properties, required };
}

function compiles(pattern: string, groups = 0): void {
  let regex: RegExp;
  try {
    regex = new RegExp(pattern, "u");
  } catch (error) {
    throw new RangeError(`invalid pattern: ${(error as Error).message}`);
  }
  if (groups && new RegExp(`${regex.source}|`, "u").exec("")!.length - 1 < groups) throw new RangeError("the pattern needs a group for the cited id");
}

/** The built-in deterministic graders, by name. */
export const GRADERS: Record<string, GraderDef> = {
  exact: {
    settings: object({}),
    deterministic: true,
    create: () => ({ grade: (s) => (jsonEqual(s.output, s.expect) ? of(true) : of(false, "the output differs from expect")) }),
  },
  field_equals: {
    shorthand: "field",
    settings: object({ field: { type: "string", minLength: 1 } }, ["field"]),
    deterministic: true,
    create: (c) => ({
      grade: (s) => {
        const field = c.field as string;
        const want = valueAt(s.expect, field);
        const got = valueAt(s.output, field);
        if (want === MISSING) return of(false, `the case expects nothing at ${field}`);
        if (got === MISSING) return of(false, `the output has no ${field}`);
        return jsonEqual(got, want) ? of(true) : of(false, `${field} differs`);
      },
    }),
  },
  numeric_close: {
    shorthand: "field",
    settings: object({ field: { anyOf: [{ type: "string", minLength: 1 }, { type: "null" }] }, tolerance: { type: "number", minimum: 0 } }),
    deterministic: true,
    create: (c) => ({
      grade: (s) => {
        const field = (c.field as string | null | undefined) ?? null;
        const where = field ?? "the output";
        const got = field === null ? s.output : valueAt(s.output, field);
        const want = field === null ? s.expect : valueAt(s.expect, field);
        if (typeof want !== "number") return of(false, `the case doesn't expect a number at ${where}`);
        if (typeof got !== "number") return of(false, `${where} isn't a number`);
        const passed = Math.abs(got - want) <= ((c.tolerance as number | undefined) ?? 1e-6);
        return passed ? of(true) : of(false, `${where} is off by more than the tolerance`);
      },
    }),
  },
  schema_valid: {
    settings: object({}),
    deterministic: true,
    create: () => ({
      grade: (s) => {
        const status = s.status ?? "completed";
        if (status !== "completed") return of(false, `the run ended ${status}`);
        const schema = s.output_schema;
        if (!schema) return s.output !== null && s.output !== undefined ? of(true) : of(false, "the run has no output");
        try {
          checkSchema(schema);
        } catch (error) {
          if (error instanceof SchemaError) return of(false, `the task's output schema can't be checked: ${error.message}`);
          throw error;
        }
        const problems = validate(s.output ?? null, schema);
        return of(problems.length === 0, problems.join("; ") || null);
      },
    }),
  },
  guard_fired: {
    shorthand: "guard",
    settings: object({ guard: STRINGS, fired: { type: "boolean" }, action: { enum: ["allow", "redact", "repair", "escalate", "require_approval", "block", "log_only"] } }, ["guard"]),
    deterministic: true,
    create: (c) => ({
      grade: (s) => {
        const fired = (c.fired as boolean | undefined) ?? true;
        const action = c.action as GuardAction | undefined;
        const wrong = texts(c.guard).filter(
          (wanted) => (s.guards ?? []).some((f) => guardMatches(f.guard, wanted) && (action === undefined || f.action === action)) !== fired,
        );
        return wrong.length ? of(false, `${wrong.join(", ")} ${fired ? "didn't fire" : "fired"}`) : of(true);
      },
    }),
  },
  status: {
    shorthand: "status",
    settings: object({ status: { anyOf: [{ enum: STATUSES }, { type: "array", minItems: 1, items: { enum: STATUSES } }] } }, ["status"]),
    deterministic: true,
    create: (c) => ({
      grade: (s) => {
        const status = s.status ?? "completed";
        return texts(c.status).includes(status) ? of(true) : of(false, `the run ended ${status}`);
      },
    }),
  },
  contains: {
    shorthand: "text",
    settings: object({ text: STRINGS, ignore_case: { type: "boolean" } }, ["text"]),
    deterministic: true,
    create: (c) => ({
      grade: (s) => {
        let text = outputText(s.output);
        let needles = texts(c.text);
        if (c.ignore_case) {
          text = text.toLowerCase();
          needles = needles.map((n) => n.toLowerCase());
        }
        const missing = needles.flatMap((needle, i) => (text.includes(needle) ? [] : [String(i + 1)]));
        return missing.length ? of(false, `text ${missing.join(", ")} of ${needles.length} not found`) : of(true);
      },
    }),
  },
  regex: {
    shorthand: "pattern",
    settings: object({ pattern: { type: "string", minLength: 1 } }, ["pattern"]),
    deterministic: true,
    create: (c) => {
      compiles(c.pattern as string);
      const pattern = new RegExp(c.pattern as string, "u");
      return { grade: (s) => (pattern.test(outputText(s.output)) ? of(true) : of(false, "the pattern doesn't match")) };
    },
  },
  citation_present: {
    shorthand: "ids",
    settings: object({ ids: { anyOf: [{ type: "string" }, { type: "array", items: { type: "string" } }] }, pattern: { type: "string" } }),
    deterministic: true,
    create: (c) => {
      const source = (c.pattern as string | undefined) ?? CITATION_PATTERN;
      compiles(source, 1);
      const pattern = new RegExp(source, "gu");
      return {
        grade: (s) => {
          const cited = new Set([...outputText(s.output).matchAll(pattern)].map((m) => m[1]));
          const wanted = c.ids === undefined ? [] : texts(c.ids);
          if (wanted.length === 0) return cited.size ? of(true) : of(false, "nothing is cited");
          const missing = wanted.filter((id) => !cited.has(id));
          return missing.length ? of(false, `${missing.join(", ")} not cited`) : of(true);
        },
      };
    },
  },
};

/**
 * The grader a spec names, built from its settings; a single setting fills its shorthand.
 *
 * @throws UnknownProvider for a grader that doesn't exist, SpecError for bad settings.
 */
export function buildGrader(spec: GraderSpec, graders: Record<string, GraderDef> = GRADERS): Evaluator {
  const def = graders[spec.use];
  if (def === undefined) throw new UnknownProvider(`no Evaluator provider '${spec.use}'`, { name: spec.use });
  let settings: Record<string, unknown>;
  if (spec.settings === null || spec.settings === undefined) settings = {};
  else if (isObject(spec.settings)) settings = spec.settings;
  else if (def.shorthand !== undefined) settings = { [def.shorthand]: spec.settings };
  else throw new SpecError(`grader ${spec.label}: ${spec.use} takes no single setting`);
  const problems = validate(settings, def.settings);
  if (problems.length) throw new SpecError(`grader ${spec.label}: ${problems.join("; ")}`);
  try {
    return def.create(settings);
  } catch (error) {
    throw new SpecError(`grader ${spec.label}: ${(error as Error).message}`);
  }
}

// --- results, baselines, sampling, shadow reports ------------------------------------------

export interface GraderResult extends Grade {
  grader: string;
}

export interface CaseResult {
  id: string;
  passed: boolean;
  status: RunStatus;
  run_id?: string | null;
  grades: GraderResult[];
  guards?: GuardFiring[];
  cost_usd?: number | null;
}

export interface SuiteResult {
  suite: string;
  task: string;
  threshold: number;
  pass_rate: number;
  passed: boolean;
  grader_rates: Record<string, number>;
  cases: CaseResult[];
}

const rate = (part: number, whole: number): number => (whole ? Math.round((part / whole) * 1e6) / 1e6 : 0);

/**
 * A suite's pass rate (to 6 decimals), whether it meets `threshold` (compared before
 * rounding), and each grader's pass rate over the cases that have it.
 */
export function summarize(suite: string, task: string, threshold: number, cases: readonly CaseResult[]): SuiteResult {
  const passed = cases.filter((c) => c.passed).length;
  const totals = new Map<string, [number, number]>();
  for (const item of cases) {
    for (const grade of item.grades) {
      const counts = totals.get(grade.grader) ?? [0, 0];
      totals.set(grade.grader, [counts[0] + Number(grade.passed), counts[1] + 1]);
    }
  }
  return {
    suite,
    task,
    threshold,
    pass_rate: rate(passed, cases.length),
    passed: cases.length > 0 && passed / cases.length >= threshold,
    grader_rates: Object.fromEntries([...totals].map(([label, [ok, all]]) => [label, rate(ok, all)])),
    cases: [...cases],
  };
}

export interface Baseline {
  suite: string;
  task: string;
  pass_rate: number;
  cases: Record<string, boolean>;
}

export interface Comparison {
  regressed: string[];
  fixed: string[];
  added: string[];
  removed: string[];
}

/** How `cases` (passed, by id) differ from `baseline`; a case that passed before and fails now regressed. */
export function compare(baseline: Baseline | null | undefined, cases: Record<string, boolean>): Comparison {
  const before = baseline?.cases ?? {};
  const ids = Object.keys(cases);
  return {
    regressed: ids.filter((i) => before[i] === true && !cases[i]).sort(),
    fixed: ids.filter((i) => before[i] === false && cases[i]).sort(),
    added: ids.filter((i) => !(i in before)).sort(),
    removed: Object.keys(before).filter((i) => !(i in cases)).sort(),
  };
}

/** Whether online evals sample a run: FNV-1a 32 of its id, over 2^32, below `rate`. */
export function sampled(runId: string, sampleRate: number): boolean {
  return sampleRate > 0 && fnv1a32(new TextEncoder().encode(runId)) / 2 ** 32 < sampleRate;
}

export interface ShadowGuardReport {
  guard: string;
  runs: number;
  would_fire: number;
  rate: number;
  false_positives: string[] | null;
  misses: string[] | null;
}

function expected(graders: readonly GraderSpec[], guard: string): boolean {
  return graders.some((spec) => {
    if (spec.use !== "guard_fired") return false;
    const settings = isObject(spec.settings) ? spec.settings : { guard: spec.settings };
    return (settings.fired ?? true) === true && texts(settings.guard).some((wanted) => guardMatches(guard, wanted));
  });
}

const wouldFire = (guard: string, fired: readonly GuardFiring[]): boolean => fired.some((f) => f.shadow && f.guard === guard);

/**
 * For each `log_only` guard: how many cases it would fire on, the rate, and the false
 * positives and misses against each case's `guard_fired` graders (R8).
 */
export function shadowReport(guards: readonly string[], cases: readonly [string, GraderSpec[], GuardFiring[]][]): ShadowGuardReport[] {
  return guards.map((guard) => {
    const fired = cases.filter(([, , f]) => wouldFire(guard, f)).map(([id]) => id);
    const wanted = new Set(cases.filter(([, graders]) => expected(graders, guard)).map(([id]) => id));
    return {
      guard,
      runs: cases.length,
      would_fire: fired.length,
      rate: rate(fired.length, cases.length),
      false_positives: fired.filter((id) => !wanted.has(id)),
      misses: cases.map(([id]) => id).filter((id) => wanted.has(id) && !fired.includes(id)),
    };
  });
}
