/** wrapModel on AI SDK mock models: redaction both ways, budgets and cost, and stream guards. */

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { LanguageModelV4GenerateResult, LanguageModelV4StreamPart } from "@ai-sdk/provider";
import { defineMiddleware, definePlugin, FakeClock, load, outcome, RunBlocked, type Plugin, type RunResult } from "@harnessweaver/core";
import { generateText, simulateReadableStream, streamText } from "ai";
import { MockLanguageModelV4 } from "ai/test";
import { describe, expect, it } from "vitest";
import { applyRequest, toRequest, wrapModel } from "../src/index.js";

function harness(spec: Record<string, unknown>, plugins: Plugin[] = []) {
  const path = join(mkdtempSync(join(tmpdir(), "hw-ai-")), "harness.yaml");
  writeFileSync(path, JSON.stringify({ apiVersion: "harnessweaver/v1", kind: "Harness", metadata: { name: "app" }, ...spec }));
  return load(path, { clock: new FakeClock(), plugins });
}

const USAGE = { inputTokens: { total: 1000, noCache: 1000, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: 500, text: 500, reasoning: 0 } };
const PRICES = { models: { prices: { "mock-model": { input_per_mtok: 1, output_per_mtok: 2 } } } };

function answer(text: string): LanguageModelV4GenerateResult {
  return { content: [{ type: "text", text }], finishReason: { unified: "stop", raw: "stop" }, usage: USAGE, warnings: [] };
}

function streamed(...deltas: string[]): { stream: ReadableStream<LanguageModelV4StreamPart> } {
  const chunks: LanguageModelV4StreamPart[] = [
    { type: "text-start", id: "t" },
    ...deltas.map((delta): LanguageModelV4StreamPart => ({ type: "text-delta", id: "t", delta })),
    { type: "text-end", id: "t" },
    { type: "finish", usage: USAGE, finishReason: { unified: "stop", raw: "stop" } },
  ];
  return { stream: simulateReadableStream({ chunks, initialDelayInMs: null, chunkDelayInMs: null }) };
}

// A plugin middleware that masks an email on the way in and a code on the way out.
const mask = definePlugin({
  namespace: "acme",
  version: "1.0.0",
  middleware: [
    defineMiddleware({
      name: "mask",
      hooks: ["model.before", "model.after"],
      fail_mode: "closed",
      handler: (event) => {
        if (event.hook === "model.before") {
          const messages = event.request.messages.map((m) => ({ ...m, content: m.content?.replaceAll("ann@example.com", "[EMAIL]") }));
          return outcome.continue({ ...event, request: { ...event.request, messages } });
        }
        if (event.hook === "model.after") return outcome.continue({ ...event, response: { ...event.response, text: event.response.text?.replaceAll("code-42", "[CODE]") } });
        return undefined;
      },
    }),
  ],
});

describe("wrapModel", () => {
  it("redacts the prompt before the model and the answer before the app, and meters the cost", async () => {
    const model = new MockLanguageModelV4({ modelId: "mock-model", doGenerate: answer("your code is code-42") });
    const h = harness({ ...PRICES, middleware: [{ use: "acme.mask" }] }, [mask]);
    let ended: RunResult | undefined;
    const text = await h.session({ onEnd: (r) => (ended = r) }, async (s) => {
      const result = await generateText({ model: wrapModel(s, model), system: "Be brief.", prompt: "I'm ann@example.com" });
      return result.text;
    });
    expect(text).toBe("your code is [CODE]");
    expect(JSON.stringify(model.doGenerateCalls[0]!.prompt)).toContain("I'm [EMAIL]");
    expect(JSON.stringify(model.doGenerateCalls[0]!.prompt)).not.toContain("ann@example.com");
    expect(ended?.cost_usd).toBeCloseTo(0.002, 9);
  });

  it("stops a call past the run's budget before it reaches the model", async () => {
    const model = new MockLanguageModelV4({ modelId: "mock-model", doGenerate: answer("hi") });
    const h = harness({ budgets: { per_run: { max_model_calls: 1 } } });
    await expect(
      h.session({}, async (s) => {
        await generateText({ model: wrapModel(s, model), prompt: "one" });
        await generateText({ model: wrapModel(s, model), prompt: "two", maxRetries: 0 });
      }),
    ).rejects.toMatchObject({ details: { code: "budget_exceeded", limit: "max_model_calls" } });
    expect(model.doGenerateCalls).toHaveLength(1);
  });

  it("runs stream guards on each delta, and closes the call with usage and model.after", async () => {
    const model = new MockLanguageModelV4({ modelId: "mock-model", doStream: streamed("write to ", "ann@example.com", " now") });
    const h = harness({ ...PRICES, guardrails: { stream: [{ id: "pii", use: "pii.regex", entities: ["EMAIL"] }] } });
    let ended: RunResult | undefined;
    const text = await h.session({ onEnd: (r) => (ended = r) }, async (s) => {
      const result = streamText({ model: wrapModel(s, model), prompt: "who?" });
      return await result.text;
    });
    expect(text).toBe("write to [EMAIL] now");
    expect(ended?.cost_usd).toBeCloseTo(0.002, 9);
    expect(ended?.trace?.filter((e) => e.hook === "model.after").length).toBeGreaterThan(0);
  });

  it("cuts a stream a guard blocks", async () => {
    const model = new MockLanguageModelV4({ modelId: "mock-model", doStream: streamed("fine, ", "forbidden words", " follow") });
    const h = harness({ guardrails: { stream: [{ use: "regex.deny", patterns: ["forbidden"], action: "block" }] } });
    const seen: string[] = [];
    await expect(
      h.session({}, async (s) => {
        const { stream } = await wrapModel(s, model).doStream({ prompt: [{ role: "user", content: [{ type: "text", text: "go" }] }] });
        for await (const part of stream) if (part.type === "text-delta") seen.push(part.delta);
      }),
    ).rejects.toBeInstanceOf(RunBlocked);
    expect(seen).toEqual(["fine, "]);
  });
});

describe("applyRequest", () => {
  it("writes changed system, user and tool text back, but never the model's own answers", () => {
    const params = {
      prompt: [
        { role: "system", content: "sys ann@example.com" },
        { role: "user", content: [{ type: "text", text: "hi ann@example.com" }] },
        { role: "assistant", content: [{ type: "text", text: "ann@example.com" }, { type: "tool-call", toolCallId: "c1", toolName: "find", input: { q: 1 } }] },
        { role: "tool", content: [{ type: "tool-result", toolCallId: "c1", toolName: "find", output: { type: "json", value: { mail: "ann@example.com" } } }] },
      ],
    } as const;
    const model = new MockLanguageModelV4({ modelId: "mock-model" });
    const [request, where] = toRequest(structuredClone(params) as never, model, null, false);
    expect(request.messages.map((m) => m.role)).toEqual(["system", "user", "assistant", "assistant", "tool"]);
    expect(request.messages[3]!.tool_calls).toEqual([{ id: "c1", name: "find", arguments: { q: 1 } }]);
    const redacted = { ...request, messages: request.messages.map((m) => ({ ...m, content: m.content?.replaceAll("ann@example.com", "[EMAIL]") })) };
    const sent = applyRequest(params as never, where, request, redacted);
    expect(sent.prompt).toEqual([
      { role: "system", content: "sys [EMAIL]" },
      { role: "user", content: [{ type: "text", text: "hi [EMAIL]" }] },
      params.prompt[2],
      { role: "tool", content: [{ type: "tool-result", toolCallId: "c1", toolName: "find", output: { type: "text", value: '{"mail":"[EMAIL]"}' } }] },
    ]);
    expect(params.prompt[0].content).toBe("sys ann@example.com");
  });
});
