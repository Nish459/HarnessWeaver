/** Runner for the `evals` suite: graders, datasets, summaries, baselines, sampling, shadow reports. */

import { describe, expect, it } from "vitest";
import { SpecError, UnknownProvider } from "../src/errors.js";
import { buildGrader, compare, gradersFor, parseGraders, readDataset, sampled, shadowReport, summarize, type CaseResult } from "../src/evals.js";
import { casesOf, type Case } from "./fixtures.js";

async function grade(c: Case) {
  const want = c.expect;
  let grader;
  try {
    const [spec] = parseGraders([c.grader]);
    grader = buildGrader(spec!);
  } catch (error) {
    if (error instanceof UnknownProvider) return expect(want).toEqual({ error: "unknown" });
    if (error instanceof SpecError || error instanceof RangeError) return expect(want).toEqual({ error: "invalid" });
    throw error;
  }
  expect(want.error, "the grader should have been refused").toBeUndefined();
  const result = await grader.grade(c.sample);
  expect(result.passed).toBe(want.passed);
  expect(result.score).toBe(want.passed ? 1 : 0);
}

function dataset(c: Case) {
  let read;
  try {
    read = readDataset(c.dataset, c.name);
  } catch (error) {
    if (error instanceof SpecError) return expect(c.expect).toEqual({ error: "invalid" });
    throw error;
  }
  expect(c.expect.error, "the dataset should have been refused").toBeUndefined();
  const labels = Object.fromEntries(read.cases.map((item) => [item.id, gradersFor(read, item).map((g) => g.label)]));
  expect(labels).toEqual(c.expect.cases);
}

describe("evals", () => {
  it.each(casesOf("evals"))("%s", async (_, c) => {
    if ("grader" in c) return grade(c);
    if ("dataset" in c) return dataset(c);
    if ("summarize" in c) {
      const cases: CaseResult[] = c.summarize.cases.map((item: Record<string, any>) => ({
        id: item.id,
        passed: item.grades.every((g: { passed: boolean }) => g.passed),
        status: "completed",
        grades: item.grades.map((g: { grader: string; passed: boolean }) => ({ grader: g.grader, passed: g.passed, score: Number(g.passed), reason: null })),
      }));
      const result = summarize("s", "t", c.summarize.threshold, cases);
      return expect({ pass_rate: result.pass_rate, passed: result.passed, grader_rates: result.grader_rates }).toEqual(c.expect);
    }
    if ("current" in c) {
      const found = compare(c.baseline, c.current.cases);
      return expect({ ...found, regression: found.regressed.length > 0 }).toEqual(c.expect);
    }
    if ("run_id" in c) return expect(sampled(c.run_id, c.rate)).toBe(c.expect.sampled);
    const cases = c.cases.map((item: Record<string, any>) => [item.id, parseGraders(item.graders), item.guards]);
    return expect(shadowReport(c.shadow_guards, cases)).toEqual(c.expect.report);
  });
});
