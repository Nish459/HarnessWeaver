/** Runners for the spec suites: `merge` (layers, locks, bounds, run budgets) and `levels`. */

import { describe, expect, it } from "vitest";
import { formatDuration } from "../src/durations.js";
import { BoundViolation, LockViolation, SpecError } from "../src/errors.js";
import { assess } from "../src/spec/levels.js";
import { specFromDocuments, validateSpec } from "../src/spec/loader.js";
import { mergeLayers } from "../src/spec/merge.js";
import { BuiltinProfiles, type ProfileResolver } from "../src/spec/sources.js";
import { casesOf, type Case } from "./fixtures.js";

const ERRORS: Record<string, new (...args: never[]) => SpecError> = {
  lock_violation: LockViolation,
  bound_violation: BoundViolation,
  spec_invalid: SpecError,
};

function expectError(want: Record<string, string>, run: () => unknown): void {
  let caught: unknown;
  try {
    run();
  } catch (error) {
    caught = error;
  }
  expect(caught, "expected an error").toBeInstanceOf(SpecError);
  const error = caught as SpecError;
  if (want.error === "spec_invalid") expect(error.constructor).toBe(SpecError);
  else expect(error).toBeInstanceOf(ERRORS[want.error ?? ""]!);
  for (const key of ["lock", "bound"]) if (key in want) expect(error.details[key]).toBe(want[key]);
}

function orgProfiles(documents: Record<string, Record<string, unknown>>): ProfileResolver {
  return {
    resolve: (ref) => {
      const document = documents[ref.name];
      return ref.scheme === "org" && document ? { layerName: `org://${ref.name}`, kind: "org", document, source: null, directory: null } : undefined;
    },
  };
}

function runBudget(c: Case) {
  const org: Record<string, unknown> = {
    apiVersion: "harnessweaver/v1",
    kind: "Profile",
    metadata: { name: "org", version: "1.0.0" },
    budgets: { per_run: c.per_run },
    ...("bounds" in c ? { bounds: c.bounds } : {}),
  };
  const app = { apiVersion: "harnessweaver/v1", kind: "Harness", metadata: { name: "app" }, extends: ["org://org"], tasks: { t: { budget: c.task_budget } } };
  const effective = specFromDocuments(app, { resolvers: [new BuiltinProfiles(), orgProfiles({ org })] });
  if ("error" in c.expect) return expectError(c.expect, () => effective.runBudget("t", c.overrides));
  const budget = effective.runBudget("t", c.overrides);
  const wire = { ...budget, deadline: typeof budget.deadline === "number" ? formatDuration(budget.deadline) : null };
  expect(wire).toEqual(c.expect.budget);
}

describe("merge", () => {
  it.each(casesOf("merge"))("%s", (_, c) => {
    if (!("layers" in c)) return runBudget(c);
    const layers = c.layers.map((l: Record<string, any>) => ({ name: l.name, kind: l.kind, data: l.data }));
    if ("error" in c.expect) return expectError(c.expect, () => mergeLayers(layers));
    const merged = mergeLayers(layers);
    expect(merged.data).toStrictEqual(c.expect.value);
    for (const [path, layer] of Object.entries(c.expect.provenance ?? {})) expect(merged.provenance.get(path)?.layer, path).toBe(layer);
  });
});

describe("levels", () => {
  it.each(casesOf("levels"))("%s", (_, c) => {
    const spec = validateSpec({ metadata: { name: "app", risk_tier: c.risk_tier }, ...c.spec });
    const report = assess(spec);
    expect(report.level).toBe(c.expect.level);
    expect(report.required).toBe(c.expect.required);
    expect(report.unmet).toEqual(c.expect.unmet);
  });
});
