/** wrapModel on AI SDK mock models: redaction both ways, budgets and cost, and stream guards. */

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { LanguageModelV4GenerateResult, LanguageModelV4StreamPart } from "@ai-sdk/provider";
import { defineMiddleware, definePlugin, FakeClock, load, ModelRefusal, outcome, RunBlocked, type Plugin, type RunResult } from "@harnessweaver/core";
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

// What a provider reports when a model declines: @ai-sdk/anthropic maps Claude's stop reason
// `refusal` to the unified `content-filter`, also what a content filter cutting an answer sets.
const DECLINED = { unified: "content-filter", raw: "refusal" } as const;

function declined(text: string): LanguageModelV4GenerateResult {
  return { ...answer(text), finishReason: DECLINED };
}

function finishing(finishReason: { unified: "stop" | "content-filter"; raw: string }, ...deltas: string[]): { stream: ReadableStream<LanguageModelV4StreamPart> } {
  const chunks: LanguageModelV4StreamPart[] = [
    { type: "text-start", id: "t" },
    ...deltas.map((delta): LanguageModelV4StreamPart => ({ type: "text-delta", id: "t", delta })),
    { type: "text-end", id: "t" },
    { type: "finish", usage: USAGE, finishReason },
  ];
  return { stream: simulateReadableStream({ chunks, initialDelayInMs: null, chunkDelayInMs: null }) };
}

function streamed(...deltas: string[]): { stream: ReadableStream<LanguageModelV4StreamPart> } {
  return finishing({ unified: "stop", raw: "stop" }, ...deltas);
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

  it("blocks a declined call once, counting its usage and keeping its text from the app", async () => {
    const model = new MockLanguageModelV4({ modelId: "mock-model", doGenerate: declined("partial answer") });
    const h = harness({ ...PRICES, middleware: [{ use: "acme.mask" }] }, [mask]);
    let ended: RunResult | undefined;
    const run = h.session({ onEnd: (r) => (ended = r) }, async (s) => {
      const result = await generateText({ model: wrapModel(s, model), prompt: "hi" });
      return result.text;
    });
    await expect(run).rejects.toBeInstanceOf(ModelRefusal);
    await expect(run).rejects.toMatchObject({ details: { code: "model_refusal" } });
    expect(model.doGenerateCalls).toHaveLength(1); // the AI SDK's retries don't re-ask it
    expect(ended?.status).toBe("blocked");
    expect(ended?.cost_usd).toBeCloseTo(0.002, 9);
    expect(ended?.trace?.filter((e) => e.code === "model_refusal").length).toBeGreaterThan(0);
    expect(ended?.trace?.filter((e) => e.hook === "model.after" && e.kind !== "note").length).toBe(0);
  });

  it("errors a declined stream at its finish, counting its usage", async () => {
    const model = new MockLanguageModelV4({ modelId: "mock-model", doStream: finishing(DECLINED, "partial ", "answer") });
    const h = harness(PRICES);
    let ended: RunResult | undefined;
    const seen: string[] = [];
    await expect(
      h.session({ onEnd: (r) => (ended = r) }, async (s) => {
        const { stream } = await wrapModel(s, model).doStream({ prompt: [{ role: "user", content: [{ type: "text", text: "go" }] }] });
        for await (const part of stream) if (part.type === "text-delta") seen.push(part.delta);
      }),
    ).rejects.toBeInstanceOf(ModelRefusal);
    expect(seen).toEqual(["partial ", "answer"]); // delivered before the signal arrived
    expect(ended?.status).toBe("blocked");
    expect(ended?.cost_usd).toBeCloseTo(0.002, 9);
    expect(ended?.trace?.filter((e) => e.code === "model_refusal").length).toBeGreaterThan(0);
  });

  it("fails streamText on a declined stream, and the run ends blocked", async () => {
    const model = new MockLanguageModelV4({ modelId: "mock-model", doStream: finishing(DECLINED, "partial") });
    let ended: RunResult | undefined;
    const run = harness(PRICES).session({ onEnd: (r) => (ended = r) }, async (s) => {
      const result = streamText({ model: wrapModel(s, model), prompt: "hi", onError: () => undefined });
      return await result.text;
    });
    await expect(run).rejects.toBeInstanceOf(ModelRefusal);
    expect(ended?.status).toBe("blocked");
    expect(ended?.cost_usd).toBeCloseTo(0.002, 9);
  });

  const PROMPT = { prompt: [{ role: "user" as const, content: [{ type: "text" as const, text: "go" }] }] };

  it("with holdStream, delivers nothing from a declined stream", async () => {
    const model = new MockLanguageModelV4({ modelId: "mock-model", doStream: finishing(DECLINED, "partial ", "answer") });
    let ended: RunResult | undefined;
    const seen: string[] = [];
    await expect(
      harness(PRICES).session({ onEnd: (r) => (ended = r) }, async (s) => {
        const { stream } = await wrapModel(s, model, { holdStream: true }).doStream(PROMPT);
        for await (const part of stream) seen.push(part.type);
      }),
    ).rejects.toBeInstanceOf(ModelRefusal);
    expect(seen).toEqual([]);
    expect(ended?.cost_usd).toBeCloseTo(0.002, 9);
  });

  it("with holdStream, releases an ordinary answer in order, after its guards", async () => {
    const model = new MockLanguageModelV4({ modelId: "mock-model", doStream: streamed("write to ", "ann@example.com") });
    const h = harness({ guardrails: { stream: [{ id: "pii", use: "pii.regex", entities: ["EMAIL"] }] } });
    const seen: string[] = [];
    await h.session({}, async (s) => {
      const { stream } = await wrapModel(s, model, { holdStream: true }).doStream(PROMPT);
      for await (const part of stream) seen.push(part.type === "text-delta" ? part.delta : part.type);
    });
    expect(seen).toEqual(["text-start", "write to ", "[EMAIL]", "text-end", "finish"]);
  });

  it("with holdStream, releases what a stream with no finish part sent", async () => {
    const chunks: LanguageModelV4StreamPart[] = [{ type: "text-start", id: "t" }, { type: "text-delta", id: "t", delta: "hi" }];
    const model = new MockLanguageModelV4({ modelId: "mock-model", doStream: { stream: simulateReadableStream({ chunks, initialDelayInMs: null, chunkDelayInMs: null }) } });
    const seen: string[] = [];
    await harness({}).session({}, async (s) => {
      const { stream } = await wrapModel(s, model, { holdStream: true }).doStream(PROMPT);
      for await (const part of stream) seen.push(part.type);
    });
    expect(seen).toEqual(["text-start", "text-delta"]);
  });

  it("with blockEmptyAnswers, blocks an answer a provider emptied of its refusal", async () => {
    const empty = { ...answer(""), content: [] };
    const generated = new MockLanguageModelV4({ modelId: "mock-model", doGenerate: empty });
    await expect(harness({}).session({}, (s) => generateText({ model: wrapModel(s, generated, { blockEmptyAnswers: true }), prompt: "hi" }))).rejects.toBeInstanceOf(ModelRefusal);
    const streaming = new MockLanguageModelV4({ modelId: "mock-model", doStream: streamed() });
    await expect(
      harness({}).session({}, async (s) => {
        const { stream } = await wrapModel(s, streaming, { blockEmptyAnswers: true }).doStream(PROMPT);
        for await (const _ of stream);
      }),
    ).rejects.toBeInstanceOf(ModelRefusal);
  });

  it("lets empty answers through by default, and a tool call is never empty", async () => {
    const empty = new MockLanguageModelV4({ modelId: "mock-model", doGenerate: { ...answer(""), content: [] } });
    const text = await harness({}).session({}, async (s) => (await generateText({ model: wrapModel(s, empty), prompt: "hi" })).text);
    expect(text).toBe(""); // a model may end a tool loop with nothing to add
    const call = { type: "tool-call", toolCallId: "c1", toolName: "find", input: "{}" } as const;
    const calling = new MockLanguageModelV4({ modelId: "mock-model", doGenerate: { ...answer(""), content: [call], finishReason: { unified: "tool-calls", raw: "tool_use" } } });
    await harness({}).session({}, async (s) => {
      const result = await wrapModel(s, calling, { blockEmptyAnswers: true }).doGenerate(PROMPT);
      expect(result.content).toHaveLength(1);
    });
    const chunks: LanguageModelV4StreamPart[] = [call, { type: "finish", usage: USAGE, finishReason: { unified: "tool-calls", raw: "tool_use" } }];
    const streaming = new MockLanguageModelV4({ modelId: "mock-model", doStream: { stream: simulateReadableStream({ chunks, initialDelayInMs: null, chunkDelayInMs: null }) } });
    const seen: string[] = [];
    await harness({}).session({}, async (s) => {
      const { stream } = await wrapModel(s, streaming, { blockEmptyAnswers: true }).doStream(PROMPT);
      for await (const part of stream) seen.push(part.type);
    });
    expect(seen).toEqual(["tool-call", "finish"]);
  });

  it("leaves other finish reasons alone", async () => {
    const model = new MockLanguageModelV4({
      modelId: "mock-model",
      doGenerate: { ...answer("cut off"), finishReason: { unified: "length", raw: "max_tokens" } },
    });
    const text = await harness({}).session({}, async (s) => (await generateText({ model: wrapModel(s, model), prompt: "hi" })).text);
    expect(text).toBe("cut off");
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
