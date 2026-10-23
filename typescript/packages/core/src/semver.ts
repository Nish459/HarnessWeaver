/**
 * Semantic versions and npm-style version ranges (fixtures suite `semver`).
 *
 * Used for profile references (`org://acme-baseline@^2`) and the contract ranges
 * plugins declare (`">=1.0,<2"`). Comparators are `1.2.3`, `=1.2.3`, `>1.2`, `>=1.2`,
 * `<2` and `<=1.4`; `^` keeps the left-most non-zero part, `~` allows patch changes,
 * and partial versions and wildcards cover what they leave open. Comparators in a set
 * are joined by commas or spaces, sets by `||`. A prerelease only matches a set with a
 * prerelease comparator on the same major.minor.patch.
 */

const NUMBER = "0|[1-9]\\d*";
const IDENT = "[0-9A-Za-z-]+";
const VERSION = new RegExp(
  `^(?<major>${NUMBER})\\.(?<minor>${NUMBER})\\.(?<patch>${NUMBER})` +
    `(?:-(?<pre>${IDENT}(?:\\.${IDENT})*))?(?:\\+(?<build>${IDENT}(?:\\.${IDENT})*))?$`,
);
const PARTIAL = new RegExp(
  `^(?<major>${NUMBER}|[xX*])(?:\\.(?<minor>${NUMBER}|[xX*]))?(?:\\.(?<patch>${NUMBER}|[xX*]))?` +
    `(?:-(?<pre>${IDENT}(?:\\.${IDENT})*))?(?:\\+${IDENT}(?:\\.${IDENT})*)?$`,
);
const COMPARATOR = /^(?<op>\^|~|>=|<=|>|<|=)?\s*(?<version>\S+)$/;
const OPERATORS = new Set(["^", "~", ">=", "<=", ">", "<", "="]);

type Identifier = number | string;
type Op = ">=" | ">" | "<" | "<=" | "=";

function parsePrerelease(text: string | undefined): Identifier[] {
  if (!text) return [];
  return text.split(".").map((part) => {
    if (!/^\d+$/.test(part)) return part;
    if (part.length > 1 && part.startsWith("0")) {
      throw new RangeError(`numeric prerelease identifier '${part}' has a leading zero`);
    }
    return Number(part);
  });
}

/** Numeric identifiers sort before alphanumeric ones (SemVer 2.0.0 No. 11). */
function compareIdentifiers(a: Identifier, b: Identifier): number {
  if (typeof a === "number" && typeof b === "number") return Math.sign(a - b);
  if (typeof a === "number") return -1;
  if (typeof b === "number") return 1;
  return a < b ? -1 : a > b ? 1 : 0;
}

/** A SemVer 2.0.0 version. Build metadata is accepted and ignored. */
export class Version {
  constructor(
    readonly major: number,
    readonly minor: number,
    readonly patch: number,
    readonly prerelease: readonly Identifier[] = [],
  ) {}

  /**
   * Parse `MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]`.
   *
   * @throws RangeError if the text isn't a valid version.
   */
  static parse(text: string): Version {
    const groups = VERSION.exec(text.trim())?.groups;
    if (groups === undefined) throw new RangeError(`invalid version '${text}'`);
    return new Version(Number(groups.major), Number(groups.minor), Number(groups.patch), parsePrerelease(groups.pre));
  }

  /** -1, 0 or 1 as this version sorts before, with or after `other`; a release sorts after its prereleases. */
  compare(other: Version): number {
    for (const [a, b] of [
      [this.major, other.major],
      [this.minor, other.minor],
      [this.patch, other.patch],
    ] as const) {
      if (a !== b) return Math.sign(a - b);
    }
    if (this.prerelease.length === 0 && other.prerelease.length === 0) return 0;
    if (this.prerelease.length === 0) return 1;
    if (other.prerelease.length === 0) return -1;
    const length = Math.max(this.prerelease.length, other.prerelease.length);
    for (let index = 0; index < length; index++) {
      const a = this.prerelease[index];
      const b = other.prerelease[index];
      if (a === undefined) return -1;
      if (b === undefined) return 1;
      const order = compareIdentifiers(a, b);
      if (order !== 0) return order;
    }
    return 0;
  }

  /** Whether `other` has the same major.minor.patch. */
  sameRelease(other: Version): boolean {
    return this.major === other.major && this.minor === other.minor && this.patch === other.patch;
  }

  toString(): string {
    const release = `${this.major}.${this.minor}.${this.patch}`;
    return this.prerelease.length ? `${release}-${this.prerelease.join(".")}` : release;
  }
}

interface Comparator {
  op: Op;
  version: Version;
}

function test(comparator: Comparator, version: Version): boolean {
  const order = version.compare(comparator.version);
  switch (comparator.op) {
    case ">=":
      return order >= 0;
    case ">":
      return order > 0;
    case "<":
      return order < 0;
    case "<=":
      return order <= 0;
    case "=":
      return order === 0;
  }
}

interface Partial {
  major: number | undefined;
  minor: number | undefined;
  patch: number | undefined;
  prerelease: Identifier[];
}

function floor(p: Partial): Version {
  return new Version(p.major ?? 0, p.minor ?? 0, p.patch ?? 0, p.prerelease);
}

function parsePartial(text: string): Partial {
  const groups = PARTIAL.exec(text)?.groups;
  if (groups === undefined) throw new RangeError(`invalid version '${text}' in range`);
  const number = (value: string | undefined): number | undefined =>
    value === undefined || value === "x" || value === "X" || value === "*" ? undefined : Number(value);
  const major = number(groups.major);
  const minor = number(groups.minor);
  const patch = number(groups.patch);
  if ((major === undefined && minor !== undefined) || (minor === undefined && patch !== undefined)) {
    throw new RangeError(`invalid version '${text}' in range; a wildcard can't precede a number`);
  }
  const prerelease = parsePrerelease(groups.pre);
  if (prerelease.length && patch === undefined) {
    throw new RangeError(`invalid version '${text}' in range; a prerelease needs a full version`);
  }
  return { major, minor, patch, prerelease };
}

function caret(p: Partial): Comparator[] {
  if (p.major === undefined) return [];
  let high: Version;
  if (p.major > 0 || p.minor === undefined) high = new Version(p.major + 1, 0, 0);
  else if (p.minor > 0 || p.patch === undefined) high = new Version(0, p.minor + 1, 0);
  else high = new Version(0, 0, p.patch + 1);
  return [{ op: ">=", version: floor(p) }, { op: "<", version: high }];
}

function tilde(p: Partial): Comparator[] {
  if (p.major === undefined) return [];
  const high = p.minor === undefined ? new Version(p.major + 1, 0, 0) : new Version(p.major, p.minor + 1, 0);
  return [{ op: ">=", version: floor(p) }, { op: "<", version: high }];
}

/** The first version after everything a partial version covers. */
function nextOpen(p: Partial): Version {
  const major = p.major ?? 0;
  return p.minor === undefined ? new Version(major + 1, 0, 0) : new Version(major, p.minor + 1, 0);
}

function desugar(op: string, p: Partial): Comparator[] {
  if (op === "^") return caret(p);
  if (op === "~") return tilde(p);
  if (p.major === undefined) {
    // "*", ">=*", ...: everything, or nothing.
    return ["", "=", ">=", "<="].includes(op) ? [] : [{ op: "<", version: new Version(0, 0, 0) }];
  }
  const full = p.patch !== undefined;
  switch (op) {
    case "":
    case "=":
      return full
        ? [{ op: "=", version: floor(p) }]
        : [
            { op: ">=", version: floor(p) },
            { op: "<", version: nextOpen(p) },
          ];
    case ">=":
      return [{ op: ">=", version: floor(p) }];
    case ">":
      return full ? [{ op: ">", version: floor(p) }] : [{ op: ">=", version: nextOpen(p) }];
    case "<":
      return [{ op: "<", version: floor(p) }];
    default: // "<="
      return full ? [{ op: "<=", version: floor(p) }] : [{ op: "<", version: nextOpen(p) }];
  }
}

function satisfies(comparators: readonly Comparator[], version: Version): boolean {
  if (!comparators.every((c) => test(c, version))) return false;
  if (version.prerelease.length === 0) return true;
  return comparators.some((c) => c.version.prerelease.length > 0 && c.version.sameRelease(version));
}

/** A set of versions in npm range syntax (see the module docs). */
export class VersionRange {
  private constructor(
    readonly text: string,
    private readonly sets: readonly (readonly Comparator[])[],
  ) {}

  /**
   * Parse a range such as `^1.2`, `>=1.0,<2` or `~1.4 || ^2`.
   *
   * @throws RangeError if the range is malformed.
   */
  static parse(text: string): VersionRange {
    const sets: Comparator[][] = [];
    for (const raw of text.split("||")) {
      const alternative = raw.trim();
      const comparators: Comparator[] = [];
      if (alternative) {
        // Allow a space between an operator and its version: ">= 1.2".
        const merged: string[] = [];
        for (const token of alternative.split(/[,\s]+/).filter(Boolean)) {
          const last = merged.at(-1);
          if (last !== undefined && OPERATORS.has(last)) merged[merged.length - 1] = last + token;
          else merged.push(token);
        }
        for (const token of merged) {
          const groups = COMPARATOR.exec(token)?.groups;
          const version = groups?.version;
          if (groups === undefined || version === undefined || "^~<>=".includes(version.charAt(0))) {
            throw new RangeError(`invalid comparator '${token}' in range '${text}'`);
          }
          comparators.push(...desugar(groups.op ?? "", parsePartial(version)));
        }
      } else if (text.includes("||")) {
        throw new RangeError(`empty alternative in range '${text}'`);
      }
      sets.push(comparators);
    }
    return new VersionRange(text.trim(), sets);
  }

  /** Whether `version` is in the range. */
  contains(version: Version | string): boolean {
    const parsed = typeof version === "string" ? Version.parse(version) : version;
    return this.sets.some((comparators) => satisfies(comparators, parsed));
  }

  /** The highest of `versions` the range contains, or undefined. */
  maxSatisfying(versions: readonly Version[]): Version | undefined {
    return versions.filter((v) => this.contains(v)).reduce<Version | undefined>(
      (best, v) => (best === undefined || v.compare(best) > 0 ? v : best),
      undefined,
    );
  }

  toString(): string {
    return this.text;
  }
}
