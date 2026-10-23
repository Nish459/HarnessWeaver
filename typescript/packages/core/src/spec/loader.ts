/**
 * Building the effective spec: documents checked, profiles resolved, layers merged
 * with locks and bounds, the result validated against the `harness` schema (with its
 * defaults), rules compiled, and the adoption level checked (DESIGNS No. 11, R1, R4,
 * R10). The same steps, in the same order, as Python's `spec_from_documents`.
 */

import { basename, dirname, extname, join } from "node:path";
import { existsSync } from "node:fs";
import type { Budget } from "../contracts.js";
import { parseDuration } from "../durations.js";
import { BoundViolation, ExpressionSyntaxError, LevelTooLow, PluginNotAllowed, SpecError } from "../errors.js";
import { compileExpression } from "../expr/index.js";
import { SCHEMAS } from "../generated/contracts.js";
import { isObject } from "../json.js";
import { validate, withDefaults, type Schema } from "../jsonschema.js";
import { RESERVED_NAMESPACES } from "../plugins/names.js";
import { RUN_POLICY_VARIABLES, TOOL_POLICY_VARIABLES } from "../policy.js";
import { assess, missingFor, REQUIREMENTS, type LevelReport } from "./levels.js";
import { checkBounds, describe, mergeLayers, originOf, type Bound, type Layer, type Lock, type Provenance, type RawMap } from "./merge.js";
import { parsePath } from "./paths.js";
import { BuiltinProfiles, ProfileDirectories, resolveExtends, type ProfileResolver } from "./sources.js";
import { loadYamlFile } from "./yaml.js";

export const API_VERSION = "harnessweaver/v1";
export const ENV_VAR = "HARNESSWEAVER_ENV";

const PROFILE_SCHEMA = SCHEMAS.profile as Schema;
const HARNESS_SCHEMA = SCHEMAS.harness as Schema;
const SECTIONS = Object.keys(PROFILE_SCHEMA.properties as object).filter((k) => !["apiVersion", "kind", "metadata", "extends", "locks", "bounds"].includes(k));
const KEYS: Record<string, Set<string>> = {
  Harness: new Set(["apiVersion", "kind", "metadata", "extends", ...SECTIONS.filter((k) => k !== "require_level")]),
  Profile: new Set(["apiVersion", "kind", "metadata", "extends", "locks", "bounds", ...SECTIONS]),
  Overlay: new Set(["apiVersion", "kind", ...SECTIONS.filter((k) => k !== "require_level")]),
};
const BODY_EXCLUDED = new Set(["apiVersion", "kind", "metadata", "extends"]);

/** Check one document's shape for its kind; `extends` given as a string becomes a list. */
export function checkDocument(document: unknown, kind: "Harness" | "Profile" | "Overlay", where: string): RawMap {
  if (!isObject(document)) throw new SpecError(`${where} must be a YAML map`);
  const version = document.apiVersion;
  if ((kind !== "Overlay" || version !== undefined) && version !== API_VERSION) {
    throw new SpecError(`${where}: apiVersion must be '${API_VERSION}', not ${JSON.stringify(version ?? null)}`);
  }
  const declared = document.kind ?? (kind === "Overlay" ? "Overlay" : null);
  if (declared !== kind) throw new SpecError(`${where}: kind must be '${kind}', not ${JSON.stringify(declared)}`);
  const allowed = KEYS[kind]!;
  const unknown = Object.keys(document).filter((k) => !allowed.has(k)).sort();
  if (unknown.length) {
    throw new SpecError(`${where}: unknown or misplaced key(s) ${unknown.join(", ")} for a ${kind} document (allowed: ${[...allowed].sort().join(", ")})`, { keys: unknown });
  }
  if (kind !== "Overlay" && !isObject(document.metadata)) throw new SpecError(`${where}: metadata (with at least a name) is required`);
  const extendsList = document.extends ?? [];
  if (typeof extendsList === "string") return { ...document, extends: [extendsList] };
  if (!Array.isArray(extendsList) || !extendsList.every((e) => typeof e === "string")) throw new SpecError(`${where}: extends must be a list of profile references`);
  return document;
}

export function layerBody(document: RawMap): RawMap {
  return Object.fromEntries(Object.entries(document).filter(([k]) => !BODY_EXCLUDED.has(k)));
}

/** A validated spec: the merged data with the schema's defaults. Sections stay plain JSON. */
export type HarnessSpec = RawMap & { metadata: RawMap & { name: string; risk_tier: string } };

/**
 * Validate a spec document against the `harness` schema, with its defaults filled in,
 * plus the model rules a schema can't state.
 *
 * @throws SpecError listing each problem with the layer that set it.
 */
export function validateSpec(data: RawMap, provenance: ReadonlyMap<string, Provenance> = new Map()): HarnessSpec {
  const problems = validate(data, HARNESS_SCHEMA).map((problem) => {
    const at = problem.slice(0, problem.indexOf(": "));
    let origin: Provenance | undefined;
    try {
      origin = originOf(parsePath(at.replace(/\[(\d+)\]/g, ".$1")), provenance);
    } catch {
      origin = undefined;
    }
    return origin ? `${problem} (from ${describe(origin)})` : problem;
  });
  const spec = withDefaults(data, HARNESS_SCHEMA) as HarnessSpec;
  for (const [name, router] of Object.entries(isObject(spec.routing) ? spec.routing : {})) {
    if (isObject(router) && router.default != null && Array.isArray(router.options) && !router.options.includes(router.default)) {
      problems.push(`routing.${name}: default '${String(router.default)}' is not one of the options`);
    }
  }
  for (const [task, files] of Object.entries(isObject(spec.evals) ? spec.evals : {})) {
    if (task !== "online" && !(Array.isArray(files) && files.every((f) => typeof f === "string"))) problems.push(`evals.${task} must be a list of dataset files`);
  }
  if (problems.length) throw new SpecError(`invalid spec:\n  ${problems.join("\n  ")}`, { problems });
  return spec;
}

/** Compile every cel-lite rule now, so a typo fails at load rather than mid-run (R4). */
function compileRules(spec: HarnessSpec): void {
  const policy = isObject(spec.policy) ? spec.policy : {};
  const check = (where: string, label: string, source: string, names: string[]): void => {
    try {
      compileExpression(source, names);
    } catch (error) {
      if (error instanceof ExpressionSyntaxError) throw new SpecError(`${where}[${label}].when: ${error.message}`, { path: `${where}[${label}]` });
      throw error;
    }
  };
  if ((policy.use ?? "cel_lite") === "cel_lite") {
    (Array.isArray(policy.rules) ? policy.rules : []).forEach((rule: RawMap, index) => {
      check("policy.rules", String(rule.id ?? index), String(rule.when), (rule.hook ?? "tool.before") === "tool.before" ? TOOL_POLICY_VARIABLES : RUN_POLICY_VARIABLES);
    });
  }
  const validation = isObject(spec.validation) ? spec.validation : {};
  (Array.isArray(validation.rules) ? validation.rules : []).forEach((rule: RawMap, index) => {
    check("validation.rules", String(rule.id ?? index), String(rule.when), ["output", "input", "task"]);
  });
}

/** Only profiles may put middleware in the baseline band (S8). */
function checkBands(data: RawMap, provenance: ReadonlyMap<string, Provenance>): void {
  for (const item of Array.isArray(data.middleware) ? data.middleware : []) {
    if (isObject(item) && item.band === "baseline") {
      const key = `middleware[${String(item.id)}].band`;
      const origin = provenance.get(key);
      if (origin === undefined || !["defaults", "profile", "org"].includes(origin.kind)) {
        throw new SpecError(`${key}: only profiles may put middleware in the baseline band, but ${origin ? describe(origin) : "an app layer"} does (RULES S8)`, { path: key });
      }
    }
  }
}

/** Plugin profiles count as using the plugin, so `plugins.allow` applies (S8). */
function checkPluginProfiles(spec: HarnessSpec, layers: readonly Provenance[]): void {
  const allow = isObject(spec.plugins) ? (spec.plugins.allow as string[] | null | undefined) : null;
  if (allow === null || allow === undefined) return;
  for (const layer of layers) {
    if (layer.layer.startsWith("profile://") && layer.layer.includes(".")) {
      const namespace = layer.layer.slice("profile://".length).split(".")[0]!;
      if (!RESERVED_NAMESPACES.has(namespace) && !allow.includes(namespace)) {
        throw new PluginNotAllowed(`${layer.layer} comes from plugin '${namespace}', which isn't in plugins.allow (${[...allow].sort().join(", ") || "(none)"})`, { namespace });
      }
    }
  }
}

const BUDGET_FIELDS = ["max_usd", "max_tokens", "max_model_calls", "max_tool_calls", "deadline"] as const;

/** A budget section as the spec writes it, with the deadline in milliseconds. */
export function budgetOf(raw: unknown): Budget {
  const value = isObject(raw) ? raw : {};
  const budget: Budget = {};
  for (const field of BUDGET_FIELDS) {
    const item = value[field];
    budget[field] = item === null || item === undefined ? null : field === "deadline" ? parseDuration(item) : (item as number);
  }
  return budget;
}

function tighter(a: Budget, b: Budget): Budget {
  const result: Budget = {};
  for (const field of BUDGET_FIELDS) {
    const x = a[field];
    const y = b[field];
    result[field] = x == null ? (y ?? null) : y == null ? x : Math.min(x, y);
  }
  return result;
}

/** The effective spec of one app, after every layer is merged. */
export class EffectiveSpec {
  constructor(
    readonly spec: HarnessSpec,
    readonly data: RawMap,
    readonly provenance: ReadonlyMap<string, Provenance>,
    readonly locks: readonly Lock[],
    readonly bounds: readonly Bound[],
    readonly layers: readonly Provenance[],
    readonly level: LevelReport,
    readonly path: string | null = null,
  ) {}

  /** The layer that set `path` (for example `budgets.per_run.max_usd`). */
  origin(path: string): Provenance | undefined {
    return originOf(parsePath(path), this.provenance);
  }

  /**
   * The budget for one run of `task`: per-run limits, tightened by the task's own.
   * `overrides` may only lower fields the task lists as `overridable` (R10).
   *
   * @throws SpecError for an unknown task; BoundViolation for an override that isn't allowed.
   */
  runBudget(task: string, overrides?: Record<string, unknown> | null): Budget {
    const tasks = isObject(this.spec.tasks) ? this.spec.tasks : {};
    const taskSpec = tasks[task];
    if (!isObject(taskSpec)) throw new SpecError(`unknown task '${task}'`, { task });
    const perRun = budgetOf(isObject(this.spec.budgets) ? this.spec.budgets.per_run : undefined);
    const budget = tighter(perRun, budgetOf(taskSpec.budget));
    if (!overrides || Object.keys(overrides).length === 0) return budget;
    const overridable = isObject(taskSpec.budget) && Array.isArray(taskSpec.budget.overridable) ? (taskSpec.budget.overridable as string[]) : [];
    for (const key of Object.keys(overrides)) {
      if (!overridable.includes(key)) {
        throw new BoundViolation(`tasks.${task}.budget.${key} can't be overridden per run; overridable: ${JSON.stringify(overridable)}`, { path: `tasks.${task}.budget.${key}` });
      }
    }
    // Each overridden field read as the spec would read it; the rest stay as they are.
    let lowered: Budget;
    try {
      lowered = { ...budget };
      for (const [key, value] of Object.entries(overrides) as [(typeof BUDGET_FIELDS)[number], unknown][]) {
        const parsed = value === null || value === undefined ? null : key === "deadline" ? parseDuration(value) : value;
        if (parsed !== null && (typeof parsed !== "number" || parsed < 0)) throw new RangeError(key);
        lowered[key] = parsed as number | null;
      }
    } catch {
      throw new BoundViolation("invalid budget override");
    }
    for (const key of Object.keys(overrides) as (typeof BUDGET_FIELDS)[number][]) {
      const old = budget[key];
      const fresh = lowered[key];
      if (fresh === null || fresh === undefined || (old !== null && old !== undefined && fresh > old)) {
        throw new BoundViolation(`a run may only lower tasks.${task}.budget.${key} (R10)`, { path: `tasks.${task}.budget.${key}` });
      }
    }
    const wire: RawMap = { ...lowered, deadline: typeof lowered.deadline === "number" ? `${lowered.deadline}ms` : null };
    checkBounds({ budgets: { per_run: wire } }, this.bounds, new Map());
    return lowered;
  }
}

export interface FromDocuments {
  resolvers?: readonly ProfileResolver[];
  overlay?: RawMap | null;
  appName?: string;
  appSource?: string | null;
  overlayName?: string | null;
  overlaySource?: string | null;
  directory?: string | null;
}

/**
 * Build the effective spec from parsed documents.
 *
 * @throws SpecError for any invalid document, unknown profile, lock or bound violation,
 *   invalid expression, or a level below the required one.
 */
export function specFromDocuments(app: RawMap, options: FromDocuments = {}): EffectiveSpec {
  const appName = options.appName ?? "harness.yaml";
  const appDoc = checkDocument({ ...app }, "Harness", options.appSource ?? appName);
  const resolvers = options.resolvers ?? [new BuiltinProfiles(), new ProfileDirectories([])];
  const defaults = new BuiltinProfiles().resolve({ text: "profile://defaults", scheme: "profile", name: "defaults", range: null })!;
  const profiles = resolveExtends(appDoc.extends as string[] | undefined ?? [], resolvers, options.directory ?? null).filter((p) => p.layerName !== defaults.layerName);
  // Built-in profiles go before org profiles, whatever order `extends` lists them in.
  profiles.sort((a, b) => Number(a.kind !== "profile") - Number(b.kind !== "profile"));
  const layers: Layer[] = [{ name: defaults.layerName, kind: defaults.kind, data: layerBody(checkDocument(defaults.document, "Profile", defaults.layerName)) }];
  for (const profile of profiles) {
    const document = checkDocument(profile.document, "Profile", profile.source ?? profile.layerName);
    layers.push({ name: profile.layerName, kind: profile.kind, data: layerBody(document), source: profile.source });
  }
  layers.push({ name: appName, kind: "app", data: layerBody(appDoc), source: options.appSource ?? null });
  if (options.overlay) {
    const name = options.overlayName ?? "overlay";
    const overlay = checkDocument({ ...options.overlay }, "Overlay", options.overlaySource ?? name);
    layers.push({ name, kind: "overlay", data: layerBody(overlay), source: options.overlaySource ?? null });
  }
  const merged = mergeLayers(layers);
  const data: RawMap = { apiVersion: API_VERSION, kind: "Harness", metadata: appDoc.metadata, extends: [...((appDoc.extends as string[] | undefined) ?? [])], ...merged.data };
  const spec = validateSpec(data, merged.provenance);
  compileRules(spec);
  checkBands(merged.data, merged.provenance);
  checkPluginProfiles(spec, merged.layers);
  const level = assess(spec);
  if (LEVELS_RANK(level.level) < LEVELS_RANK(level.required)) {
    const missing = missingFor(level, level.required);
    throw new LevelTooLow(
      `${spec.metadata.name} reaches ${level.level} but its risk tier '${spec.metadata.risk_tier}' requires ${level.required}. Missing: ${missing.map((c) => REQUIREMENTS[c]).join("; ")}`,
      { reached: level.level, required: level.required, missing },
    );
  }
  return new EffectiveSpec(spec, merged.data, merged.provenance, merged.locks, merged.bounds, merged.layers, level, options.appSource ?? null);
}

const LEVELS_RANK = (level: string): number => ["L0", "L1", "L2", "L3", "L4"].indexOf(level);

export interface LoadOptions {
  /** The overlay `harness.<env>.yaml`; defaults to `$HARNESSWEAVER_ENV`. A missing file is fine. */
  env?: string | null;
  /** Extra directories to search for `org://` profiles. */
  profileDirs?: readonly string[];
  /** Replace the default profile resolvers. */
  resolvers?: readonly ProfileResolver[];
  /** Resolvers to try after the built-in profiles, such as plugin profiles. */
  extraResolvers?: readonly ProfileResolver[];
}

/**
 * Load `harness.yaml` with its profiles and environment overlay.
 *
 * @throws SpecError; see `specFromDocuments`.
 */
export function loadSpec(path: string, options: LoadOptions = {}): EffectiveSpec {
  const document = loadYamlFile(path);
  if (!isObject(document)) throw new SpecError(`${path} must be a YAML map`);
  const directory = dirname(path);
  const resolvers = options.resolvers ?? [new BuiltinProfiles(), ...(options.extraResolvers ?? []), ProfileDirectories.fromEnvironment(directory, options.profileDirs ?? [])];
  const env = options.env ?? (process.env[ENV_VAR] || null);
  const suffix = extname(path);
  const overlayPath = env ? join(directory, `${basename(path, suffix)}.${env}${suffix}`) : null;
  let overlay: RawMap | null = null;
  if (overlayPath && existsSync(overlayPath)) {
    const loaded = loadYamlFile(overlayPath);
    if (!isObject(loaded)) throw new SpecError(`${overlayPath} must be a YAML map`);
    overlay = loaded;
  }
  return specFromDocuments(document, {
    resolvers,
    overlay,
    appName: basename(path),
    appSource: path,
    overlayName: overlay && overlayPath ? basename(overlayPath) : null,
    overlaySource: overlay ? overlayPath : null,
    directory,
  });
}
