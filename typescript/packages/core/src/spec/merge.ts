/**
 * Layered merging of spec documents, with provenance, locks and bounds (DESIGNS No. 11,
 * fixtures suite `merge`).
 *
 * - Layers merge in order: defaults, built-in profiles, org profiles, the app's own
 *   profiles, the app, an overlay.
 * - Scalars and plain lists: the later layer wins. Maps merge key by key.
 * - Keyed lists (guard stages, middleware, routing cascades, rule lists) merge by `id`:
 *   a known id updates its item in place, new items are appended. Items without an id
 *   get `<use>#<n>` after merging (`rule#<n>` in rule lists, `item#<n>` otherwise).
 * - `null` can unset a scalar, but can't remove a map or a keyed list.
 * - A profile's lock covers that path and everything under it for later layers, and
 *   `*` and `[*]` in it match any key and any item;
 *   changing a locked value is a LockViolation (R1), restating it is fine (ADR-0018).
 * - Bounds accumulate and are checked on the result: out of bounds is a
 *   BoundViolation, never clamped (R10). Bounds on `budgets.per_run.<field>` also
 *   apply to every task's budget. A `null` at a path with a maximum removes the limit,
 *   so it's a BoundViolation too.
 */

import { formatDuration, parseDuration } from "../durations.js";
import { BoundViolation, LockViolation, SpecError } from "../errors.js";
import { isObject } from "../json.js";
import { formatPath, isItem, isPrefix, matches, parsePath, type Segment, type SpecPath } from "./paths.js";

export type LayerKind = "defaults" | "profile" | "org" | "app" | "overlay";
export type RawMap = { [key: string]: unknown };

export const isProfileKind = (kind: LayerKind): boolean => kind === "defaults" || kind === "profile" || kind === "org";

/** The layer a value came from. */
export interface Provenance {
  layer: string;
  kind: LayerKind;
  source?: string | null;
}

export const describe = (p: Provenance): string => (p.source ? `${p.layer} (${p.source})` : p.layer);

/** One spec document to merge: its body, without apiVersion, kind, metadata and extends. */
export interface Layer {
  name: string;
  kind: LayerKind;
  data: RawMap;
  source?: string | null;
}

export interface Lock {
  path: Segment[];
  declaredBy: Provenance;
  text: string;
}

/** min/max for a path pattern: numbers, or durations in milliseconds. */
export interface Bound {
  path: Segment[];
  text: string;
  minimum: number | null;
  maximum: number | null;
  durations: boolean;
  declaredBy: Provenance;
}

export interface Merged {
  data: RawMap;
  provenance: Map<string, Provenance>;
  locks: Lock[];
  bounds: Bound[];
  layers: Provenance[];
}

const KEYED_LISTS = ["guardrails.*", "middleware", "routing.*.cascade", "policy.rules", "validation.rules", "tasks.*.guardrails.*"].map(parsePath);
const PROFILE_ONLY = ["locks", "bounds", "require_level"];
const AUTO = "~auto";
const FORBIDDEN_KEY = "__proto__"; // assigning it would set a prototype, not a key

const isKeyed = (path: SpecPath): boolean => KEYED_LISTS.some((pattern) => matches(pattern, path));

/** Equality that keeps bools apart from numbers, as YAML and JSON do. */
function same(a: unknown, b: unknown): boolean {
  if (isObject(a) && isObject(b)) {
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every((k) => Object.hasOwn(b, k) && same(a[k], b[k]));
  }
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => same(x, b[i]));
  return a === b;
}

/** Expand shorthands so layers merge field by field. */
function normalize(body: RawMap): RawMap {
  if (isObject(body.tasks)) {
    for (const task of Object.values(body.tasks)) if (isObject(task) && typeof task.runner === "string") task.runner = { use: task.runner };
  }
  if (isObject(body.tools) && typeof body.tools.manifests === "string") body.tools.manifests = [body.tools.manifests];
  return body;
}

class Merger {
  data: RawMap = {};
  provenance = new Map<string, Provenance>();
  locks: Lock[] = [];
  private auto = 0;

  checkLocks(path: SpecPath): void {
    for (const lock of this.locks) {
      if (isPrefix(lock.path, path)) {
        throw new LockViolation(`${formatPath(path)} is locked by ${describe(lock.declaredBy)} (lock '${lock.text}'); it can't be changed (R1)`, {
          path: formatPath(path),
          lock: lock.text,
        });
      }
    }
  }

  /** A replaced subtree must not contain locked values either. */
  checkSubtreeLocks(path: SpecPath): void {
    this.checkLocks(path);
    for (const lock of this.locks) {
      if (isPrefix(lock.path.slice(0, path.length), path)) {
        throw new LockViolation(`replacing ${formatPath(path)} would change ${lock.text}, which ${describe(lock.declaredBy)} locked (R1)`, {
          path: formatPath(path),
          lock: lock.text,
        });
      }
    }
  }

  mergeValue(path: Segment[], present: unknown, incoming: unknown, prov: Provenance): unknown {
    const where = formatPath(path);
    const current = present === undefined ? null : present; // a missing key reads as null, as in Python
    if (incoming === null) {
      if (isObject(current) || (Array.isArray(current) && isKeyed(path))) {
        throw new SpecError(`${where} can't be removed by setting it to null (in ${describe(prov)})`, { path: where });
      }
      return this.setLeaf(path, current, null, prov);
    }
    if ((current === null || current === undefined) && (isObject(incoming) || Array.isArray(incoming))) this.checkLocks(path);
    if (Array.isArray(current) && isKeyed(path) && !Array.isArray(incoming)) throw new SpecError(`${where} must stay a list (in ${describe(prov)})`, { path: where });
    if (isObject(incoming)) {
      if (current === null || current === undefined || isObject(current)) return this.mergeMap(path, isObject(current) ? current : undefined, incoming, prov);
      return this.replace(path, current, incoming, prov);
    }
    if (Array.isArray(incoming) && isKeyed(path)) {
      if (current === null || current === undefined || Array.isArray(current)) return this.mergeKeyed(path, Array.isArray(current) ? current : [], incoming, prov);
      return this.replace(path, current, incoming, prov);
    }
    if (isObject(current)) return this.replace(path, current, incoming, prov);
    return this.setLeaf(path, current, incoming, prov);
  }

  setLeaf(path: SpecPath, current: unknown, incoming: unknown, prov: Provenance): unknown {
    const key = formatPath(path);
    const changed = !same(current, incoming);
    if (changed) this.checkLocks(path);
    if (changed || !this.provenance.has(key)) this.provenance.set(key, prov);
    return structuredClone(incoming);
  }

  replace(path: SpecPath, current: unknown, incoming: unknown, prov: Provenance): unknown {
    if (same(current, incoming)) return current;
    this.checkSubtreeLocks(path);
    const prefix = formatPath(path);
    for (const key of [...this.provenance.keys()]) {
      if (key === prefix || key.startsWith(`${prefix}.`) || key.startsWith(`${prefix}[`)) this.provenance.delete(key);
    }
    this.provenance.set(prefix, prov);
    return structuredClone(incoming);
  }

  mergeMap(path: Segment[], current: RawMap | undefined, incoming: RawMap, prov: Provenance): RawMap {
    const result: RawMap = { ...(current ?? {}) };
    for (const [key, value] of Object.entries(incoming)) {
      if (key === FORBIDDEN_KEY) {
        const where = formatPath([...path, key]);
        throw new SpecError(`${where}: ${key} can't be a key (in ${describe(prov)})`, { path: where });
      }
      // Only the map's own keys: a key named `constructor` has no value here yet.
      result[key] = this.mergeValue([...path, key], Object.hasOwn(result, key) ? result[key] : undefined, value, prov);
    }
    return result;
  }

  mergeKeyed(path: Segment[], current: unknown[], incoming: unknown[], prov: Provenance): unknown[] {
    const where = formatPath(path);
    const result = [...current];
    const positions = new Map<string, number>();
    result.forEach((existing, index) => {
      if (isObject(existing) && typeof existing.id === "string") positions.set(existing.id, index);
    });
    for (const raw of incoming) {
      if (!isObject(raw)) throw new SpecError(`items of ${where} must be maps`, { path: where });
      let item = raw;
      let id = item.id;
      if (id === null || id === undefined) {
        this.auto += 1;
        id = `${AUTO}${this.auto}~`;
        item = { ...item, id };
      } else if (typeof id !== "string" || !id) {
        throw new SpecError(`ids in ${where} must be non-empty strings`, { path: where });
      } else if (id.startsWith(AUTO)) {
        // Only the merger makes these: a layer naming one could reach an id-less item
        // that a lock can only name by its final id (R1).
        throw new SpecError(`ids in ${where} can't start with ${AUTO}`, { path: where });
      }
      const itemPath = [...path, { id: id as string }];
      const position = positions.get(id as string);
      if (position !== undefined) {
        result[position] = this.mergeMap(itemPath, result[position] as RawMap, item, prov);
      } else {
        positions.set(id as string, result.length);
        result.push(this.mergeMap(itemPath, undefined, item, prov));
      }
    }
    return result;
  }

  /** Give items merged without an id their `<use>#<n>` ids, and move their provenance. */
  assignAutoIds(): void {
    const renames = new Map<string, string>();
    for (const [path, items] of keyedLists(this.data)) {
      const entries = items.filter(isObject);
      const taken = new Set(entries.map((e) => String(e.id)));
      const counters = new Map<string, number>();
      for (const entry of entries) {
        const current = String(entry.id ?? "");
        if (!current.startsWith(AUTO)) continue;
        const use = String(entry.use ?? (path.at(-1) === "rules" ? "rule" : "item"));
        let candidate: string;
        do {
          counters.set(use, (counters.get(use) ?? 0) + 1);
          candidate = `${use}#${counters.get(use)}`;
        } while (taken.has(candidate));
        taken.add(candidate);
        renames.set(formatPath([...path, { id: current }]), formatPath([...path, { id: candidate }]));
        entry.id = candidate;
      }
    }
    if (renames.size === 0) return;
    const updated = new Map<string, Provenance>();
    for (let [key, prov] of this.provenance) {
      for (const [old, fresh] of renames) {
        if (key === old || key.startsWith(`${old}.`) || key.startsWith(`${old}[`)) {
          key = fresh + key.slice(old.length);
          break;
        }
      }
      updated.set(key, prov);
    }
    this.provenance = updated;
  }
}

function* keyedLists(data: unknown, path: Segment[] = []): Generator<[Segment[], unknown[]]> {
  if (!isObject(data)) return;
  for (const [key, value] of Object.entries(data)) {
    const child = [...path, key];
    if (Array.isArray(value) && isKeyed(child)) {
      yield [child, value];
      for (const item of value) yield* keyedLists(item, [...child, { id: isObject(item) ? String(item.id) : "" }]);
    } else {
      yield* keyedLists(value, child);
    }
  }
}

function readLocks(raw: unknown, prov: Provenance): Lock[] {
  if (!Array.isArray(raw) || !raw.every((t) => typeof t === "string")) throw new SpecError(`locks in ${describe(prov)} must be a list of paths`);
  return raw.map((text: string) => {
    try {
      return { path: parsePath(text), declaredBy: prov, text: formatPath(parsePath(text)) };
    } catch (error) {
      throw new SpecError(`${(error as Error).message} (in ${describe(prov)})`);
    }
  });
}

function limitOf(value: unknown, path: string, prov: Provenance): [number | null, boolean] {
  if (value === null || value === undefined) return [null, false];
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new SpecError(`bound on ${path} in ${describe(prov)} must be finite`);
    return [value, false];
  }
  if (typeof value === "string") {
    try {
      return [parseDuration(value), true];
    } catch (error) {
      throw new SpecError(`bound on ${path} in ${describe(prov)}: ${(error as Error).message}`);
    }
  }
  throw new SpecError(`bound on ${path} in ${describe(prov)} must be a number or a duration`);
}

function readBounds(raw: unknown, prov: Provenance): Bound[] {
  if (!isObject(raw)) throw new SpecError(`bounds in ${describe(prov)} must be a map of path to {min, max}`);
  return Object.entries(raw).map(([text, spec]) => {
    const where = `bound on ${text} in ${describe(prov)}`;
    if (!isObject(spec) || Object.keys(spec).length === 0 || !Object.keys(spec).every((k) => k === "min" || k === "max")) {
      throw new SpecError(`${where} must have min and/or max`);
    }
    let path: Segment[];
    try {
      path = parsePath(text);
    } catch (error) {
      throw new SpecError(`${(error as Error).message} (in ${describe(prov)})`);
    }
    const [minimum, minDuration] = limitOf(spec.min, text, prov);
    const [maximum, maxDuration] = limitOf(spec.max, text, prov);
    if (minimum !== null && maximum !== null) {
      if (minDuration !== maxDuration) throw new SpecError(`${where} mixes a number and a duration`);
      if (minimum > maximum) throw new SpecError(`${where} has min above max`);
    }
    return { path, text, minimum, maximum, durations: minimum !== null ? minDuration : maxDuration, declaredBy: prov };
  });
}

function* valuesAt(data: unknown, pattern: SpecPath, path: Segment[] = []): Generator<[Segment[], unknown]> {
  if (path.length === pattern.length) {
    yield [path, data];
    return;
  }
  const want = pattern[path.length]!;
  if (isItem(want)) {
    for (const item of Array.isArray(data) ? data : []) {
      if (isObject(item) && (want.id === "*" || item.id === want.id)) yield* valuesAt(item, pattern, [...path, { id: String(item.id ?? "") }]);
    }
    return;
  }
  if (!isObject(data)) return;
  const keys = want === "*" ? Object.keys(data) : Object.hasOwn(data, want) ? [want] : [];
  for (const key of keys) yield* valuesAt(data[key], pattern, [...path, key]);
}

/**
 * Check every merged value against every bound that covers it (R10).
 *
 * @throws BoundViolation on the first value outside a bound.
 */
export function checkBounds(data: RawMap, bounds: readonly Bound[], provenance: ReadonlyMap<string, Provenance>): void {
  for (const bound of bounds) {
    if (bound.minimum === null && bound.maximum === null) continue;
    const patterns: SpecPath[] = [bound.path];
    // Task budgets may not exceed what the org allows per run.
    if (bound.path.length === 3 && bound.path[0] === "budgets" && bound.path[1] === "per_run") patterns.push(["tasks", "*", "budget", bound.path[2]!]);
    for (const pattern of patterns) {
      for (const [path, value] of valuesAt(data, pattern)) {
        if (value === null || value === undefined) continue;
        const key = formatPath(path);
        const origin = provenance.get(key);
        const where = origin ? ` (set by ${describe(origin)})` : "";
        let measured: number;
        try {
          if (bound.durations) measured = parseDuration(value);
          else if (typeof value === "number" && Number.isFinite(value)) measured = value;
          else throw new TypeError("not a finite number");
        } catch {
          throw new SpecError(`${key}${where} can't be compared with the bound ${bound.text}`, { path: key });
        }
        const show = (limit: number): string => (bound.durations ? formatDuration(limit) : String(limit));
        if (bound.maximum !== null && measured > bound.maximum) {
          throw new BoundViolation(`${key} = ${show(measured)}${where} is above the maximum ${show(bound.maximum)} that ${describe(bound.declaredBy)} allows (R10)`, { path: key, bound: bound.text });
        }
        if (bound.minimum !== null && bound.minimum > measured) {
          throw new BoundViolation(`${key} = ${show(measured)}${where} is below the minimum ${show(bound.minimum)} that ${describe(bound.declaredBy)} allows (R10)`, { path: key, bound: bound.text });
        }
      }
    }
  }
}

/**
 * Refuse a layer's `null` at a path with a maximum: it removes the limit (R10).
 *
 * This checks merged layers only. `checkBounds` also sees a run's budget, where an unset
 * field is normal. A null the framework defaults left in place removes nothing, and a null
 * on a task budget leaves the per-run limit in force, so neither is refused.
 *
 * @throws BoundViolation on the first such value.
 */
function checkRemovedLimits(data: RawMap, bounds: readonly Bound[], provenance: ReadonlyMap<string, Provenance>): void {
  for (const bound of bounds) {
    if (bound.maximum === null) continue;
    for (const [path, value] of valuesAt(data, bound.path)) {
      const key = formatPath(path);
      const origin = provenance.get(key);
      if (value === null && origin !== undefined && origin.kind !== "defaults") {
        const limit = bound.durations ? formatDuration(bound.maximum) : String(bound.maximum);
        throw new BoundViolation(`${key} = null (set by ${describe(origin)}) removes the maximum ${limit} that ${describe(bound.declaredBy)} allows (R10)`, { path: key, bound: bound.text });
      }
    }
  }
}

/**
 * Merge spec layers in order and check bounds.
 *
 * @throws LockViolation, BoundViolation, or SpecError for a malformed layer (such as an
 *   app declaring locks).
 */
export function mergeLayers(layers: readonly Layer[]): Merged {
  const merger = new Merger();
  const bounds: Bound[] = [];
  const applied: Provenance[] = [];
  for (const layer of layers) {
    const prov: Provenance = { layer: layer.name, kind: layer.kind, source: layer.source ?? null };
    const body = normalize(structuredClone(layer.data));
    if (!isProfileKind(layer.kind)) {
      const declared = PROFILE_ONLY.filter((key) => key in body).sort();
      if (declared.length) throw new SpecError(`${describe(prov)} declares ${declared.join(", ")}, which only profiles may`, { layer: layer.name });
    }
    const locks = readLocks(body.locks ?? [], prov);
    const layerBounds = readBounds(body.bounds ?? {}, prov);
    delete body.locks;
    delete body.bounds;
    merger.data = merger.mergeMap([], merger.data, body, prov);
    merger.locks.push(...locks); // a layer's own locks bind only later layers
    bounds.push(...layerBounds);
    applied.push(prov);
  }
  merger.assignAutoIds();
  checkBounds(merger.data, bounds, merger.provenance);
  checkRemovedLimits(merger.data, bounds, merger.provenance);
  return { data: merger.data, provenance: merger.provenance, locks: merger.locks, bounds, layers: applied };
}

/** The layer that set `path`, or of its nearest ancestor. */
export function originOf(path: SpecPath, provenance: ReadonlyMap<string, Provenance>): Provenance | undefined {
  for (let length = path.length; length > 0; length--) {
    const found = provenance.get(formatPath(path.slice(0, length)));
    if (found) return found;
  }
  return undefined;
}
