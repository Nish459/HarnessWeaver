/** Every fixture suite has a TypeScript runner, as in Python (R11). */

import { describe, expect, it } from "vitest";
import { suites } from "./fixtures.js";

export const SUITES_WITH_RUNNERS = [
  "budgets",
  "bus",
  "durations",
  "evals",
  "expr",
  "governor",
  "guards",
  "hook_order",
  "levels",
  "merge",
  "outcomes",
  "plugins",
  "routing",
  "semver",
];

describe("conformance", () => {
  it("has a runner for every suite", () => {
    expect(suites()).toEqual(SUITES_WITH_RUNNERS);
  });
});
