/** Runner for the `guards` suite: each built-in guard, and the pipeline on the bus. */

import { describe, expect, it } from "vitest";
import { HookBus } from "../src/bus.js";
import { FakeClock } from "../src/clock.js";
import { withRun, type RunScope } from "../src/current.js";
import { newEnvelope } from "../src/envelope.js";
import { BUILTIN_GUARDS } from "../src/guards/providers.js";
import { guardHandler, STAGE_HOOKS, type Guard, type Stage } from "../src/guards/pipeline.js";
import type { Guardrail } from "../src/guards/common.js";
import type { HookEvent } from "../src/hooks.js";
import { buildProvider } from "../src/plugins/provider.js";
import { RunTrace } from "../src/trace.js";
import { casesOf } from "./fixtures.js";

function provider(name: string, config: Record<string, unknown> = {}): Guardrail {
  const found = BUILTIN_GUARDS.find((p) => p.name === name);
  if (found === undefined) throw new Error(`no guard ${name}`);
  return buildProvider(found, config);
}

function env() {
  return newEnvelope({ tenant: "t", principal: "p", clock: new FakeClock() });
}

function scope(contextIds: string[], trace: RunTrace): RunScope {
  return { trace, contextIds: new Set(contextIds), markPrivate: () => {}, markUntrusted: () => {} };
}

function eventOf(stage: Stage, content: any, approved: boolean): HookEvent {
  switch (stage) {
    case "input":
      return { hook: "input.before", input: content };
    case "output":
      return {
        hook: "output.before",
        output: content,
        approval: approved ? { approval_id: "a1", decision: "approve", approver: { id: "bob" } } : null,
      };
    case "tool_result":
      return { hook: "tool.after", call: { id: "c1", name: "lookup" }, tool: { name: "lookup" }, result: { call_id: "c1", output: content } };
    case "stream":
      return { hook: "stream.chunk", request: { messages: [{ role: "user", content: "q" }] }, chunk: { index: 0, delta: content } };
    default:
      return { hook: "context.after", source: "kb", items: (content as [string, string][]).map(([id, text]) => ({ id, content: text, source: "kb" })) };
  }
}

function contentOfEvent(stage: Stage, event: HookEvent): unknown {
  switch (event.hook) {
    case "input.before":
      return event.input;
    case "output.before":
      return event.output;
    case "tool.after":
      return event.result.output;
    case "stream.chunk":
      return event.chunk.delta;
    case "context.after":
      return event.items.map((item) => [item.id, item.content]);
    default:
      throw new Error(`unexpected ${stage}`);
  }
}

describe("guards", () => {
  it.each(casesOf("guards"))("%s", async (_, c) => {
    const want = c.expect;
    if ("guard" in c) {
      const guard = provider(c.guard, c.config ?? {});
      const trace = new RunTrace(new FakeClock());
      const result = "context_ids" in c
        ? await withRun(scope(c.context_ids, trace), async () => guard.check(c.content, env()))
        : await guard.check(c.content, env());
      expect(result.action).toBe(want.action);
      expect(result.content ?? null).toStrictEqual(want.content);
      expect([...new Set((result.findings ?? []).map((f) => f.type))].sort()).toEqual(want.findings);
      if ("score" in want) expect(result.score).toBeCloseTo(want.score, 9);
      return;
    }
    const stage = c.stage as Stage;
    const groups: Record<string, any>[][] = [];
    for (const spec of c.guards) {
      const last = groups.at(-1);
      if (spec.parallel && last && last.at(-1)!.parallel) last.push(spec);
      else groups.push([spec]);
    }
    const bus = new HookBus();
    for (const members of groups) {
      const guards: Guard[] = members.map((spec) => ({
        id: spec.id,
        provider: provider(spec.use, spec.config ?? {}),
        action: spec.action ?? null,
        mode: spec.mode ?? "enforce",
      }));
      const label = guards.map((g) => g.id).join("+");
      bus.add({ name: label, handler: guardHandler(stage, guards, label), hooks: new Set([STAGE_HOOKS[stage]]), band: "app", failMode: "closed" });
    }
    const trace = new RunTrace(new FakeClock());
    const result = await withRun(scope([], trace), () =>
      bus.emit(STAGE_HOOKS[stage], eventOf(stage, c.content, c.approved ?? false) as never, env(), trace),
    );
    expect(result.outcome.kind).toBe(want.outcome);
    expect(contentOfEvent(stage, result.event)).toStrictEqual(want.content);
    if ("note" in want) {
      expect(trace.events.some((e) => (e.reason ?? "").includes(want.note)), JSON.stringify(trace.events.map((e) => e.reason))).toBe(true);
    }
  });
});
