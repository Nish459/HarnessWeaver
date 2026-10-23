/** Runners for the `durations`, `semver`, `outcomes` and `hook_order` suites. */

import { describe, expect, it } from "vitest";
import { formatDuration, parseDuration } from "../src/durations.js";
import { directionOf, executionOrder, HOOK_POINTS, type Band, type HookPoint } from "../src/hooks.js";
import { mostSevere, severity, type Outcome } from "../src/outcomes.js";
import { Version, VersionRange } from "../src/semver.js";
import { casesOf } from "./fixtures.js";

describe("durations", () => {
  it.each(casesOf("durations"))("%s", (_, c) => {
    if (c.expect.error) {
      expect(() => parseDuration(c.input)).toThrow(RangeError);
      return;
    }
    const ms = parseDuration(c.input);
    expect(ms).toBe(c.expect.ms);
    expect(formatDuration(ms)).toBe(c.expect.canonical);
    expect(parseDuration(c.expect.canonical)).toBe(ms);
  });
});

describe("semver", () => {
  it.each(casesOf("semver"))("%s", (_, c) => {
    const want = c.expect;
    if ("version" in c) {
      if (want?.error) expect(() => Version.parse(c.version)).toThrow(RangeError);
      else expect(Version.parse(c.version).toString()).toBe(want.canonical);
    } else if ("compare" in c) {
      const [a, b] = (c.compare as string[]).map((v) => Version.parse(v));
      expect(a!.compare(b!)).toBe(want);
      expect(b!.compare(a!)).toBe(0 - want);
    } else if (want.error) {
      expect(() => VersionRange.parse(c.range)).toThrow(RangeError);
    } else {
      const range = VersionRange.parse(c.range);
      for (const v of want.matches) expect(range.contains(v), `${c.range} should match ${v}`).toBe(true);
      for (const v of want.rejects) expect(range.contains(v), `${c.range} should reject ${v}`).toBe(false);
    }
  });
});

/** An outcome as the fixtures write it, with Python's defaults filled in. */
function outcomeOf(raw: Record<string, unknown>): Outcome {
  return { ...raw, kind: (raw.kind as Outcome["kind"]) ?? "continue" } as Outcome;
}

describe("outcomes", () => {
  it.each(casesOf("outcomes"))("%s", (_, c) => {
    if ("outcome" in c) {
      expect(severity(outcomeOf(c.outcome))).toBe(c.expect.severity);
      return;
    }
    const outcomes = (c.outcomes as Record<string, unknown>[]).map(outcomeOf);
    const result = mostSevere(outcomes);
    expect(result.kind).toBe(c.expect.kind);
    if (c.expect.index === null) expect(outcomes.includes(result)).toBe(false);
    else expect(result).toBe(outcomes[c.expect.index]);
  });
});

describe("hook_order", () => {
  it.each(casesOf("hook_order"))("%s", (_, c) => {
    if ("directions" in c) {
      expect(new Set(HOOK_POINTS)).toEqual(new Set(Object.keys(c.directions)));
      for (const [hook, direction] of Object.entries(c.directions)) {
        expect(directionOf(hook as HookPoint)).toBe(direction);
      }
      return;
    }
    const middleware = c.middleware as { name: string; band: Band }[];
    const ordered = executionOrder(middleware, c.hook as HookPoint, (m) => m.band);
    expect(ordered.map((m) => m.name)).toEqual(c.expect);
  });
});
