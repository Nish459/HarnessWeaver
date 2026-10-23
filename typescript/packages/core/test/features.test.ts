/** Plugins, governed tools, model budgets, prompts, the sidecar client, and contract drift. */

import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  defineMiddleware,
  definePlugin,
  defineProvider,
  FakeClock,
  load,
  PluginNotAllowed,
  ProviderError,
  RunBlocked,
  RunEscalated,
  SidecarClient,
  SpecError,
  type GuardResult,
} from "../src/index.js";
import { render, TARGET } from "../scripts/sync-contracts.mjs";

let directory: string;

beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), "hw-ts-"));
});

afterEach(() => {
  delete process.env.TEST_HARNESSD_TOKEN;
});

function project(spec: Record<string, unknown>, files: Record<string, string> = {}): string {
  for (const [name, text] of Object.entries(files)) {
    mkdirSync(join(directory, name, ".."), { recursive: true });
    writeFileSync(join(directory, name), text);
  }
  const path = join(directory, "harness.yaml");
  writeFileSync(path, JSON.stringify({ apiVersion: "harnessweaver/v1", kind: "Harness", metadata: { name: "app" }, ...spec }));
  return path;
}

const REFUND_MANIFEST = JSON.stringify({
  apiVersion: "harnessweaver/v1",
  kind: "Tool",
  metadata: { name: "refund_payment" },
  spec: {
    description: "Refund a payment.",
    input_schema: { type: "object", properties: { amount_usd: { type: "number", minimum: 0 } }, required: ["amount_usd"] },
    side_effect: "write_external",
    egress: ["payments.example"],
    approval: { when: "args.amount_usd > 100", approver_role: "finance" },
  },
});

describe("plugins", () => {
  const acme = definePlugin({
    namespace: "acme",
    version: "1.0.0",
    providers: [
      defineProvider({
        port: "Guardrail",
        name: "banned_words",
        deterministic: true,
        settings: { properties: { words: { type: "array", items: { type: "string" }, default: ["darn"] } } },
        create: (s) => ({
          check: (content: string): GuardResult =>
            (s.words as string[]).some((w) => content.includes(w)) ? { action: "block", reason: "a banned word", findings: [{ type: "banned" }] } : { action: "allow" },
        }),
      }),
    ],
    middleware: [defineMiddleware({ name: "tag", hooks: ["input.before"], fail_mode: "closed", handler: () => ({ kind: "continue", note: "tagged" }) })],
  });

  it("qualifies bare names and runs the plugin's guard and middleware from the spec", async () => {
    expect(acme.providers[0]!.name).toBe("acme.banned_words");
    const path = project({ guardrails: { input: [{ id: "words", use: "acme.banned_words" }] }, middleware: [{ use: "acme.tag" }] });
    const h = load(path, { plugins: [acme], clock: new FakeClock() });
    expect(h.hooks()["input.before"]).toEqual(["guardrails.input[words]", "acme.tag"]);
    await expect(h.session({}, (s) => s.guard("input", "well darn"))).rejects.toBeInstanceOf(RunBlocked);
  });

  it("refuses a plugin outside plugins.allow, and a name outside its namespace", () => {
    const path = project({ plugins: { allow: ["openai"] }, guardrails: { input: [{ use: "acme.banned_words" }] } });
    expect(() => load(path, { plugins: [acme] })).toThrow(PluginNotAllowed);
    expect(() => definePlugin({ namespace: "acme", version: "1.0.0", middleware: [defineMiddleware({ name: "other.tag", hooks: ["run.end"], fail_mode: "open", handler: () => undefined })] })).toThrow(/outside its namespace/);
  });
});

describe("tools", () => {
  it("governs calls to tools given in code: schema, approvals, the trifecta, sanitizing", async () => {
    const refunds: number[] = [];
    const path = project({ tools: { manifests: ["tools/*.tool.yaml"], trifecta: "block" } }, { "tools/refund.tool.yaml": REFUND_MANIFEST });
    const h = load(path, { clock: new FakeClock(), tools: { refund_payment: ({ amount_usd }) => (refunds.push(amount_usd as number), { refunded: amount_usd ?? 0 }) } });
    expect(await h.session({}, (s) => s.tool("refund_payment", { amount_usd: 20 }))).toEqual({ refunded: 20 });
    await expect(h.session({}, (s) => s.tool("refund_payment", { amount_usd: -5 }))).rejects.toMatchObject({ details: { code: "schema_invalid" } });
    // A TypeScript session can't wait for a person: an approval escalates.
    await expect(h.session({}, (s) => s.tool("refund_payment", { amount_usd: 500 }))).rejects.toBeInstanceOf(RunEscalated);
    await expect(
      h.session({}, async (s) => {
        s.run.markUntrusted("test");
        s.run.markPrivate("test");
        return s.tool("refund_payment", { amount_usd: 20 });
      }),
    ).rejects.toMatchObject({ details: { code: "trifecta" } });
    await expect(h.session({}, (s) => s.tool("wire_money", {}))).rejects.toMatchObject({ details: { code: "tool_unknown" } });
    expect(refunds).toEqual([20]);
  });
});

describe("models", () => {
  it("meters a wrapped model's calls against the budget", async () => {
    const path = project({ budgets: { per_run: { max_model_calls: 1 } }, models: { prices: { "gpt-test": { input_per_mtok: 1, output_per_mtok: 2 } } } });
    const h = load(path, { clock: new FakeClock() });
    const call = async () => ({ model: "gpt-test", text: "hi", usage: { input_tokens: 1000, output_tokens: 500 } });
    let cost: number | null | undefined;
    await expect(
      h.session({ onEnd: (r) => (cost = r.cost_usd) }, async (s) => {
        await s.generate({ model: "gpt-test", messages: [{ role: "user", content: "hello" }] }, call);
        await s.generate({ model: "gpt-test", messages: [{ role: "user", content: "again" }] }, call);
      }),
    ).rejects.toMatchObject({ details: { code: "budget_exceeded", limit: "max_model_calls" } });
    expect(cost).toBeCloseTo(0.002, 9);
  });

  it("re-asks once on a Retry at model.after, then blocks with retry_exhausted", async () => {
    const retry = definePlugin({ namespace: "acme", version: "1.0.0", middleware: [defineMiddleware({ name: "picky", hooks: ["model.after"], fail_mode: "closed", handler: () => ({ kind: "retry", reason: "not good enough" }) })] });
    const h = load(project({ middleware: [{ use: "acme.picky" }] }), { plugins: [retry], clock: new FakeClock() });
    let calls = 0;
    const call = async () => (calls++, { text: "meh" });
    await expect(h.session({}, (s) => s.generate({ messages: [] }, call))).rejects.toMatchObject({ details: { code: "retry_exhausted" } });
    expect(calls).toBe(2);
  });
});

describe("prompts", () => {
  it("renders the highest matching version, and refuses a missing variable", async () => {
    const path = project({}, { "prompts/answer@1.0.0.md": "old {question}", "prompts/answer@1.2.0.md": "Q: {question} {{literal}}" });
    const h = load(path, { clock: new FakeClock() });
    expect(await h.session({}, (s) => s.prompt("answer@1", { question: "why?" }))).toBe("Q: why? {literal}");
    await expect(h.session({}, (s) => s.prompt("answer@1", {}))).rejects.toBeInstanceOf(SpecError);
  });
});

describe("sidecar", () => {
  it("runs a where: sidecar guard in harnessd, with the bearer token", async () => {
    const sent: { url: string; auth: string | null; body: Record<string, unknown> }[] = [];
    const fakeFetch = (async (url: string, init: RequestInit) => {
      sent.push({ url, auth: new Headers(init.headers).get("Authorization"), body: JSON.parse(String(init.body)) });
      return new Response(JSON.stringify({ action: "redact", content: "mail [EMAIL]", findings: [{ type: "EMAIL", private: true }] }), { status: 200 });
    }) as typeof fetch;
    process.env.TEST_HARNESSD_TOKEN = "sk-test-sidecar";
    const path = project({ sidecar: { url: "http://127.0.0.1:7070", token_env: "TEST_HARNESSD_TOKEN" }, guardrails: { input: [{ id: "pii", use: "presidio.pii", where: "sidecar", entities: ["EMAIL"] }] } });
    const sidecar = new SidecarClient({ url: "http://127.0.0.1:7070", tokenEnv: "TEST_HARNESSD_TOKEN", fetch: fakeFetch });
    const h = load(path, { clock: new FakeClock(), sidecar });
    expect(await h.session({ principal: "alice" }, (s) => s.guard("input", "mail ann@example.com"))).toBe("mail [EMAIL]");
    expect(sent[0]!.url).toBe("http://127.0.0.1:7070/v1/guards/providers/presidio.pii:check");
    expect(sent[0]!.auth).toBe("Bearer sk-test-sidecar");
    expect(sent[0]!.body).toMatchObject({ content: "mail ann@example.com", settings: { entities: ["EMAIL"] }, stage: "input", envelope: { principal: { id: "alice" } } });
  });

  it("maps harnessd's errors back to the taxonomy, and never calls out in test mode", async () => {
    const answer = new Response(JSON.stringify({ code: "not_found", type: "NotFound", message: "no run run_x", retryable: false, details: {} }), { status: 404 });
    const client = new SidecarClient({ url: "http://127.0.0.1:7070", token: "sk-test", fetch: (async () => answer) as unknown as typeof fetch });
    await expect(client.getRun("run_x")).rejects.toMatchObject({ code: "not_found" });
    expect(process.env.HARNESSWEAVER_TEST_MODE).toBe("1"); // test/setup.ts
    await expect(new SidecarClient({ url: "http://127.0.0.1:7070", token: "sk-test" }).health()).rejects.toBeInstanceOf(ProviderError);
  });

  it("needs sidecar.url for a where: sidecar guard", () => {
    const path = project({ guardrails: { input: [{ use: "presidio.pii", where: "sidecar" }] } });
    expect(() => load(path)).toThrow(/needs sidecar.url/);
  });
});

describe("contracts", () => {
  it("carries the current schemas and built-in profiles", () => {
    expect(readFileSync(TARGET, "utf8"), "run: node scripts/sync-contracts.mjs").toBe(render());
  });
});
