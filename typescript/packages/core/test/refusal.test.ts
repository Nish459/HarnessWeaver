/** A model that declines still costs tokens: the run counts them, and then ends blocked. */

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { FakeClock, load, ModelRefusal, RunBlocked, defineMiddleware, definePlugin, outcome, type ModelRequest, type RunResult } from "../src/index.js";

const SPENT = { model: "m", usage: { input_tokens: 1000, output_tokens: 500 }, finish_reason: "content-filter" };
const REQUEST: ModelRequest = { model: "m", messages: [{ role: "user", content: "hi" }] };

// Blocks with its own code if model.after ever fires, so a test can see that it didn't.
const noticing = definePlugin({
  namespace: "acme",
  version: "1.0.0",
  middleware: [defineMiddleware({ name: "notice", hooks: ["model.after"], fail_mode: "closed", handler: () => outcome.block("saw the answer", "saw_the_answer") })],
});

function harness() {
  const path = join(mkdtempSync(join(tmpdir(), "hw-refusal-")), "harness.yaml");
  const spec = {
    apiVersion: "harnessweaver/v1",
    kind: "Harness",
    metadata: { name: "app" },
    models: { prices: { m: { input_per_mtok: 1, output_per_mtok: 2 } } },
    middleware: [{ use: "acme.notice" }],
  };
  writeFileSync(path, JSON.stringify(spec));
  return load(path, { clock: new FakeClock(), plugins: [noticing] });
}

describe("ModelRefusal", () => {
  it("is a blocked error with the refusal code, and carries what the call used", () => {
    const error = new ModelRefusal(undefined, SPENT, { category: "cyber" });
    expect(error).toBeInstanceOf(RunBlocked);
    expect(error.response).toBe(SPENT);
    expect(error.toInfo()).toMatchObject({ code: "blocked", type: "ModelRefusal", details: { code: "model_refusal", category: "cyber" } });
    expect(new ModelRefusal().response).toEqual({});
  });

  it("counts a declined call, notes it on the trace and skips model.after", async () => {
    let ended: RunResult | undefined;
    const run = harness().session({ onEnd: (r) => (ended = r) }, (s) =>
      s.generate(REQUEST, async () => {
        throw new ModelRefusal(undefined, SPENT);
      }),
    );
    await expect(run).rejects.toMatchObject({ details: { code: "model_refusal" } });
    expect(ended?.status).toBe("blocked");
    expect(ended?.usage).toMatchObject({ input_tokens: 1000, output_tokens: 500 });
    expect(ended?.cost_usd).toBeCloseTo(0.002, 9);
    expect(ended?.trace?.filter((e) => e.code === "model_refusal").length).toBeGreaterThan(0);
    expect(ended?.trace?.filter((e) => e.source === "harness.budget").length).toBeGreaterThan(0);
  });

  it("lets a model's other errors through uncounted", async () => {
    let ended: RunResult | undefined;
    const run = harness().session({ onEnd: (r) => (ended = r) }, (s) =>
      s.generate(REQUEST, async () => {
        throw new TypeError("the model broke");
      }),
    );
    await expect(run).rejects.toBeInstanceOf(TypeError);
    expect(ended?.usage?.input_tokens ?? 0).toBe(0);
  });
});
