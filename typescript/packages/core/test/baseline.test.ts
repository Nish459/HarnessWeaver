/** Who owns a profile, and the other ways an app could shed a baseline control (R1, R2, R10). */

import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { load, LockViolation, SpecError } from "../src/index.js";
import { validate } from "../src/jsonschema.js";
import { budgetOf, loadSpec, specFromDocuments } from "../src/spec/loader.js";
import { mergeLayers } from "../src/spec/merge.js";

const HARNESS = { apiVersion: "harnessweaver/v1", kind: "Harness", metadata: { name: "x" } };
const PROFILE = { apiVersion: "harnessweaver/v1", kind: "Profile" };
const BASE_PII = { id: "base-pii", use: "pii.regex", action: "redact" };

let root: string;
let platform: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "hw-baseline-"));
  platform = join(root, "platform");
});

function write(path: string, document: Record<string, unknown>): string {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(document));
  return path;
}

function baseline(body: Record<string, unknown> = {}, version = "1.1.0"): void {
  write(join(platform, "acme-baseline.yaml"), {
    ...PROFILE,
    metadata: { name: "acme-baseline", version },
    guardrails: { input: [BASE_PII] },
    locks: ["observability.capture_content", "guardrails.input[base-pii]"],
    ...body,
  });
}

function app(body: Record<string, unknown>): string {
  return write(join(root, "app", "harness.yaml"), { ...HARNESS, ...body });
}

const appFile = (name: string, body: Record<string, unknown> = {}): string => write(join(root, "app", name), { ...PROFILE, metadata: { name: "app-file" }, ...body });
const disablePii = { guardrails: { input: [{ id: "base-pii", enabled: false }] } };
const names = (path: string): string[] => loadSpec(path, { env: "", profileDirs: [platform] }).layers.slice(1).map((l) => l.layer);

describe("profile ownership (ADR-0043)", () => {
  it("doesn't let an app copy outrank the platform's profile", () => {
    baseline();
    appFile(".harness/profiles/acme-baseline.yaml", { metadata: { name: "acme-baseline", version: "1.99.0" } });
    const path = app({ extends: ["org://acme-baseline@^1"], observability: { capture_content: true } });
    expect(() => loadSpec(path, { env: "", profileDirs: [platform] })).toThrow(LockViolation);
  });

  it("doesn't fall through to an app copy when the app narrows the range", () => {
    baseline();
    appFile(".harness/profiles/acme-baseline.yaml", { metadata: { name: "acme-baseline", version: "1.99.0" } });
    const path = app({ extends: ["org://acme-baseline@^1.2"] });
    expect(() => loadSpec(path, { env: "", profileDirs: [platform] })).toThrow(/can't find profile/);
  });

  it("picks the highest version in the owning directory", () => {
    baseline();
    write(join(platform, "acme-baseline@1.2.0.yaml"), { ...PROFILE, metadata: { name: "acme-baseline", version: "1.2.0" } });
    expect(names(app({ extends: ["org://acme-baseline@^1"] }))[0]).toBe("org://acme-baseline@1.2.0");
  });

  it.each([
    ["./pre.yaml", "pre.yaml"],
    ["org://pre", ".harness/profiles/pre.yaml"],
  ])("merges the app's profile %s after the platform's", (reference, file) => {
    baseline();
    appFile(file, disablePii);
    const path = app({ extends: [reference, "org://acme-baseline@^1"] });
    expect(() => loadSpec(path, { env: "", profileDirs: [platform] })).toThrow(/base-pii/);
  });

  it("treats a file an app profile names as the app's too", () => {
    baseline();
    appFile("team.yaml", { extends: ["./pre.yaml"] });
    appFile("pre.yaml");
    expect(names(app({ extends: ["./team.yaml", "org://acme-baseline@^1"] }))).toEqual(["org://acme-baseline@1.1.0", "./pre.yaml", "./team.yaml", "harness.yaml"]);
  });

  it("keeps a platform profile's file parent as the platform's", () => {
    write(join(platform, "acme-baseline.yaml"), { ...PROFILE, metadata: { name: "acme-baseline", version: "1.0.0" }, extends: ["common.yaml"] });
    write(join(platform, "common.yaml"), { ...PROFILE, metadata: { name: "common" }, guardrails: { input: [BASE_PII] }, locks: ["guardrails.input[base-pii]"] });
    appFile("pre.yaml", disablePii);
    const path = app({ extends: ["./pre.yaml", "org://acme-baseline@^1"] });
    expect(() => loadSpec(path, { env: "", profileDirs: [platform] })).toThrow(/base-pii/);
  });

  it("keeps a file both the app and the platform name as the platform's", () => {
    write(join(platform, "acme-baseline.yaml"), { ...PROFILE, metadata: { name: "acme-baseline", version: "1.0.0" }, extends: ["common.yaml"] });
    write(join(platform, "common.yaml"), { ...PROFILE, metadata: { name: "common" } });
    appFile("pre.yaml");
    expect(names(app({ extends: ["./pre.yaml", "../platform/common.yaml", "org://acme-baseline@^1"] }))).toEqual(["common.yaml", "org://acme-baseline@1.0.0", "./pre.yaml", "harness.yaml"]);
  });

  it("keeps the platform's parent when an app file has the same reference text", () => {
    write(join(platform, "acme-baseline.yaml"), { ...PROFILE, metadata: { name: "acme-baseline", version: "1.0.0" }, extends: ["common.yaml"] });
    write(join(platform, "common.yaml"), { ...PROFILE, metadata: { name: "common" }, observability: { capture_content: false }, locks: ["observability.capture_content"] });
    appFile("common.yaml");
    const path = app({ extends: ["common.yaml", "org://acme-baseline@^1"], observability: { capture_content: true } });
    expect(() => loadSpec(path, { env: "", profileDirs: [platform] })).toThrow(/capture_content/);
  });

  it("doesn't call the same reference text in another directory a cycle", () => {
    write(join(root, "a", "x.yaml"), { ...PROFILE, metadata: { name: "a" }, extends: ["../b/x.yaml"] });
    write(join(root, "b", "x.yaml"), { ...PROFILE, metadata: { name: "b" } });
    const path = write(join(root, "harness.yaml"), { ...HARNESS, extends: ["a/x.yaml", "b/x.yaml"] });
    expect(loadSpec(path, { env: "" }).layers.slice(1).map((l) => l.layer)).toEqual(["../b/x.yaml", "a/x.yaml", "harness.yaml"]);
  });

  it("still finds a real cycle", () => {
    write(join(root, "a.yaml"), { ...PROFILE, metadata: { name: "a" }, extends: ["./b.yaml"] });
    write(join(root, "b.yaml"), { ...PROFILE, metadata: { name: "b" }, extends: ["./a.yaml"] });
    const path = write(join(root, "harness.yaml"), { ...HARNESS, extends: ["./a.yaml"] });
    expect(() => loadSpec(path, { env: "" })).toThrow(/cycle/);
  });
});

describe("a locked guard on the sidecar", () => {
  const remote = (locks: string[], extra: Record<string, unknown> = {}): string => {
    write(join(platform, "base.yaml"), {
      ...PROFILE,
      metadata: { name: "base", version: "1.0.0" },
      sidecar: { url: "http://127.0.0.1:7070" },
      guardrails: { input: [{ id: "pii", use: "acme.pii", where: "sidecar", ...extra }] },
      locks,
    });
    return app({ extends: ["org://base@^1"] });
  };

  it.each([["guardrails.input[pii]"], ["guardrails.input[*]"], ["guardrails.input[pii].enabled"]])("needs sidecar.url locked under %s", (lock) => {
    expect(() => loadSpec(remote([lock]), { env: "", profileDirs: [platform] })).toThrow(/sidecar\.url/);
  });

  it.each([[["guardrails.input[pii]", "sidecar.url"]], [["guardrails.input[pii]", "sidecar"]], [["models"]]])("loads with locks %j", (locks) => {
    expect(() => loadSpec(remote(locks), { env: "", profileDirs: [platform] })).not.toThrow();
  });

  it("ignores a disabled guard", () => {
    expect(() => loadSpec(remote(["guardrails.input[pii]"], { enabled: false }), { env: "", profileDirs: [platform] })).not.toThrow();
  });

  it("covers task guards", () => {
    write(join(platform, "base.yaml"), {
      ...PROFILE,
      metadata: { name: "base", version: "1.0.0" },
      sidecar: { url: "http://127.0.0.1:7070" },
      tasks: { t: { guardrails: { input: [{ id: "g", use: "acme.pii", where: "sidecar" }] } } },
      locks: ["tasks.t.guardrails.input[g]"],
    });
    expect(() => loadSpec(app({ extends: ["org://base@^1"] }), { env: "", profileDirs: [platform] })).toThrow(/sidecar\.url/);
  });
});

describe("baseline guards in a parallel group", () => {
  it("can't hide one that fails open", () => {
    baseline({
      guardrails: {
        input: [
          { id: "a", use: "pii.regex", parallel: true },
          { id: "b", use: "pii.regex", parallel: true, fail_mode: "open" },
        ],
      },
      locks: [],
    });
    expect(() => load(app({ extends: ["org://acme-baseline@^1"] }), { profileDirs: [platform] })).toThrow(/guardrails\.input\[b\].*R2/);
  });
});

describe("values that aren't finite, and prototype-named keys", () => {
  it("refuses NaN at a bound", () => {
    const layers = [
      { name: "org", kind: "org" as const, data: { bounds: { "budgets.per_run.max_usd": { max: 5 } } } },
      { name: "app", kind: "app" as const, data: { budgets: { per_run: { max_usd: Number.NaN } } } },
    ];
    expect(() => mergeLayers(layers)).toThrow(/can't be compared/);
  });

  it("doesn't count NaN as a number", () => {
    expect(validate(Number.NaN, { type: "number" })).toHaveLength(1);
    expect(validate(Number.POSITIVE_INFINITY, { anyOf: [{ type: "number" }, { type: "null" }] })).toHaveLength(1);
  });

  it("refuses a budget that isn't finite", () => {
    expect(() => budgetOf({ max_usd: Number.NaN })).toThrow(SpecError);
  });

  it("validates a task named after an Object.prototype member", () => {
    const tasks = (body: Record<string, unknown>): Record<string, unknown> => ({ ...HARNESS, tasks: { constructor: body } });
    expect(() => specFromDocuments(tasks({ bogus: 1 }))).toThrow(/bogus/);
    expect(() => specFromDocuments(tasks({ budget: { max_usd: Number.NaN } }))).toThrow(SpecError);
    const effective = specFromDocuments(tasks({ budget: { max_usd: 1 } }));
    expect(effective.runBudget("constructor").max_usd).toBe(1);
  });
});
