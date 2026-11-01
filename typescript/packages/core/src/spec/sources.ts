/**
 * Finding the profiles a spec `extends` (DESIGNS No. 11):
 *
 * - `profile://rag` is a built-in profile; `profile://acme.baseline@^1` comes from the
 *   plugin that owns `acme`.
 * - `org://acme-baseline@^2` is an org profile on the profile search path:
 *   `HARNESSWEAVER_PROFILE_PATH`, then `.harness/profiles` next to the app spec. Files
 *   are `<name>.yaml` or `<name>@<version>.yaml`. The first directory holding any file for
 *   a name owns that name, and the highest version there that matches the range wins.
 * - Anything else is a file path, relative to the document that names it.
 *
 * A profile can extend others; parents come before the profile itself.
 *
 * A profile is app-owned when the app's team can write it: it's in `.harness/profiles` next
 * to the app spec, or it's a file named by the app spec or another app-owned profile.
 * Everything else belongs to the platform. The loader merges app-owned profiles after the
 * platform's, so the platform's locks bind them (R1, ADR-0043).
 */

import { existsSync, readdirSync, statSync } from "node:fs";
import { delimiter, dirname, isAbsolute, join, resolve } from "node:path";
import { SpecError } from "../errors.js";
import { PROFILES } from "../generated/contracts.js";
import { isObject } from "../json.js";
import { RESERVED_NAMESPACES } from "../plugins/names.js";
import { Version, VersionRange } from "../semver.js";
import type { LayerKind, RawMap } from "./merge.js";
import { loadYaml, loadYamlFile } from "./yaml.js";

export const PROFILE_PATH_ENV = "HARNESSWEAVER_PROFILE_PATH";
const REF = /^(?<scheme>profile|org):\/\/(?<name>[A-Za-z0-9._-]+)(?:@(?<range>.+))?$/;

export interface ProfileRef {
  text: string;
  scheme: "profile" | "org" | "file";
  name: string;
  range: VersionRange | null;
}

/** @throws SpecError for a malformed version range. */
export function parseRef(text: string): ProfileRef {
  const groups = REF.exec(text.trim())?.groups;
  if (groups === undefined) return { text, scheme: "file", name: text.trim(), range: null };
  let range: VersionRange | null = null;
  if (groups.range) {
    try {
      range = VersionRange.parse(groups.range);
    } catch (error) {
      throw new SpecError(`extends '${text}': ${(error as Error).message}`);
    }
  }
  return { text, scheme: groups.scheme as "profile" | "org", name: groups.name!, range };
}

export interface ResolvedProfile {
  layerName: string;
  kind: LayerKind;
  document: RawMap;
  source: string | null;
  /** Where its own relative references resolve from. */
  directory: string | null;
  /** The app's team can write it, so it merges after the platform's. */
  appOwned?: boolean;
}

/**
 * What makes two profiles the same one: the file, for a profile read from a file. The name
 * won't do: two files can be named by the same relative text.
 */
const identityOf = (profile: ResolvedProfile): string => (profile.directory !== null && profile.source !== null ? resolve(profile.source) : profile.layerName);

/** Finds profiles; returns undefined to let the next resolver try. */
export interface ProfileResolver {
  resolve(ref: ProfileRef, relativeTo: string | null): ResolvedProfile | undefined;
}

function versionOf(document: RawMap): Version | undefined {
  const text = isObject(document.metadata) ? document.metadata.version : undefined;
  if (typeof text !== "string") return undefined;
  try {
    return Version.parse(text);
  } catch {
    return undefined;
  }
}

function checkRange(ref: ProfileRef, document: RawMap, where: string): Version | undefined {
  const version = versionOf(document);
  if (ref.range !== null && (version === undefined || !ref.range.contains(version))) {
    throw new SpecError(`extends '${ref.text}': ${where} has ${version === undefined ? "no version" : `version ${version}`}, outside ${ref.range}`);
  }
  return version;
}

function asDocument(value: unknown, where: string): RawMap {
  if (!isObject(value)) throw new SpecError(`${where} is not a map`);
  return value;
}

/** The profiles shipped inside the core (`profile://<name>`). */
export class BuiltinProfiles implements ProfileResolver {
  resolve(ref: ProfileRef): ResolvedProfile | undefined {
    if (ref.scheme !== "profile" || ref.name.includes(".")) return undefined;
    const text = PROFILES[ref.name];
    if (text === undefined) return undefined;
    const document = asDocument(loadYaml(text, `profile://${ref.name}`), `built-in profile '${ref.name}'`);
    checkRange(ref, document, `profile://${ref.name}`);
    return { layerName: `profile://${ref.name}`, kind: ref.name === "defaults" ? "defaults" : "profile", document, source: null, directory: null };
  }
}

/** Org profiles (`org://name@range`) and files, from search directories. */
export class ProfileDirectories implements ProfileResolver {
  /** Search `directories` in order; `appDirectory` is the one the app's team owns. */
  constructor(
    readonly directories: readonly string[],
    readonly appDirectory: string | null = null,
  ) {}

  /** Search `extra`, then `HARNESSWEAVER_PROFILE_PATH`, then `.harness/profiles` next to the app. */
  static fromEnvironment(appDirectory: string | null, extra: readonly string[] = []): ProfileDirectories {
    const fromEnv = (process.env[PROFILE_PATH_ENV] ?? "").split(delimiter).filter(Boolean);
    if (!appDirectory) return new ProfileDirectories([...extra, ...fromEnv]);
    const appProfiles = join(appDirectory, ".harness", "profiles");
    return new ProfileDirectories([...extra, ...fromEnv, appProfiles], appProfiles);
  }

  resolve(ref: ProfileRef, relativeTo: string | null): ResolvedProfile | undefined {
    if (ref.scheme === "file") return this.file(ref, relativeTo);
    if (ref.scheme !== "org") return undefined;
    // The first directory holding the name owns it. Versions are never compared across
    // directories, or a later directory could outrank an earlier one with a higher number.
    for (const directory of this.directories) {
      let names: string[] = [];
      try {
        names = readdirSync(directory).filter((n) => n.startsWith(`${ref.name}@`) && n.endsWith(".yaml")).sort();
      } catch {
        continue;
      }
      const paths = [`${ref.name}.yaml`, ...names].map((name) => join(directory, name)).filter((path) => existsSync(path) && statSync(path).isFile());
      if (paths.length === 0) continue;
      const candidates: [Version | undefined, string, RawMap][] = [];
      for (const path of paths) {
        const document = asDocument(loadYamlFile(path), path);
        const version = versionOf(document);
        if (ref.range === null || (version !== undefined && ref.range.contains(version))) candidates.push([version, path, document]);
      }
      if (candidates.length === 0) return undefined;
      // The highest version wins; a profile with a version beats one without.
      const [version, path, document] = candidates.reduce((best, c) => {
        const [a, b] = [best[0], c[0]];
        if (a === undefined) return b === undefined ? best : c;
        return b !== undefined && b.compare(a) > 0 ? c : best;
      });
      return { layerName: version ? `org://${ref.name}@${version}` : `org://${ref.name}`, kind: "org", document, source: path, directory: dirname(path), appOwned: directory === this.appDirectory };
    }
    return undefined;
  }

  private file(ref: ProfileRef, relativeTo: string | null): ResolvedProfile | undefined {
    const path = isAbsolute(ref.name) || relativeTo === null ? ref.name : join(relativeTo, ref.name);
    if (!existsSync(path) || !statSync(path).isFile()) return undefined;
    return { layerName: ref.name, kind: "org", document: asDocument(loadYamlFile(path), path), source: path, directory: dirname(path) };
  }
}

/** Profiles plugins contribute: `profile://<namespace>.<name>[@range]`, as YAML text. */
export class PluginProfiles implements ProfileResolver {
  constructor(private readonly plugins: readonly { namespace: string; profiles: Readonly<Record<string, string>> }[]) {}

  resolve(ref: ProfileRef): ResolvedProfile | undefined {
    if (ref.scheme !== "profile" || !ref.name.includes(".")) return undefined;
    const [namespace = "", name = ""] = [ref.name.slice(0, ref.name.indexOf(".")), ref.name.slice(ref.name.indexOf(".") + 1)];
    if (RESERVED_NAMESPACES.has(namespace)) return undefined;
    const plugin = this.plugins.find((p) => p.namespace === namespace);
    if (plugin === undefined) return undefined;
    const text = plugin.profiles[name];
    if (text === undefined) {
      const offered = Object.keys(plugin.profiles).sort().join(", ") || "none";
      throw new SpecError(`plugin '${namespace}' has no profile '${name}' (it has: ${offered})`, { reference: ref.text });
    }
    const document = asDocument(loadYaml(text, `profile://${ref.name}`), `profile://${ref.name}`);
    const version = checkRange(ref, document, `profile://${ref.name}`);
    return { layerName: version ? `profile://${ref.name}@${version}` : `profile://${ref.name}`, kind: "org", document, source: `plugin ${namespace}`, directory: null };
  }
}

/**
 * Resolve references and their own `extends`, parents first, without duplicates.
 *
 * `extendsList` is the app spec's list, so the files it names are app-owned, and so are the
 * files an app-owned profile names (ADR-0043).
 *
 * @throws SpecError for a reference that can't be found, a cycle, or a bad document.
 */
export function resolveExtends(extendsList: readonly string[], resolvers: readonly ProfileResolver[], relativeTo: string | null, stack: readonly string[] = [], namedByApp = true): ResolvedProfile[] {
  const resolved: ResolvedProfile[] = [];
  // Each profile once. A file both the app and the platform name stays the platform's.
  const add = (profile: ResolvedProfile): void => {
    const index = resolved.findIndex((r) => identityOf(r) === identityOf(profile));
    if (index === -1) resolved.push(profile);
    else if (resolved[index]!.appOwned && !profile.appOwned) resolved[index] = profile;
  };
  for (const text of extendsList) {
    const ref = parseRef(text);
    let found: ResolvedProfile | undefined;
    for (const resolver of resolvers) {
      found = resolver.resolve(ref, relativeTo);
      if (found) break;
    }
    if (found === undefined) throw new SpecError(`can't find profile '${text}'; see ${PROFILE_PATH_ENV}`, { reference: text });
    if (ref.scheme === "file" && namedByApp) found = { ...found, appOwned: true };
    const identity = identityOf(found);
    if (stack.includes(identity)) throw new SpecError(`profiles extend each other in a cycle: ${[...stack, identity].join(" -> ")}`);
    if (found.document.kind !== "Profile") throw new SpecError(`${found.layerName} must be a document of kind Profile`);
    let parents = found.document.extends ?? [];
    if (typeof parents === "string") parents = [parents];
    if (!Array.isArray(parents)) throw new SpecError(`extends in ${found.layerName} must be a list`);
    for (const parent of resolveExtends(parents.map(String), resolvers, found.directory ?? relativeTo, [...stack, identity], found.appOwned === true)) add(parent);
    add(found);
  }
  return resolved;
}
