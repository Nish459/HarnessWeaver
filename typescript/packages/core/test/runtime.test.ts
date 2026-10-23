/** Runners for the runtime suites: `bus`, `budgets` and `plugins`. */

import { describe, expect, it } from "vitest";
import { BudgetMeter, resolveCost } from "../src/budgets.js";
import { HookBus } from "../src/bus.js";
import { FakeClock } from "../src/clock.js";
import type { ModelRequest } from "../src/contracts.js";
import { newEnvelope } from "../src/envelope.js";
import { SpecError } from "../src/errors.js";
import type { HookEvent, HookPoint } from "../src/hooks.js";
import type { Registration } from "../src/middleware.js";
import type { Outcome } from "../src/outcomes.js";
import { checkNamespace, isAllowed, ownerOf, ownershipProblem, qualify } from "../src/plugins/names.js";
import { RunTrace } from "../src/trace.js";
import { casesOf } from "./fixtures.js";

// --- bus -------------------------------------------------------------------------------

function eventOf(hook: string, value: unknown): HookEvent {
  if (hook === "input.before") return { hook: "input.before", input: value as never };
  if (hook === "output.before") return { hook: "output.before", output: value as never };
  return { hook: "run.end", status: "completed", output: value as never };
}

function valueOf(event: HookEvent): unknown {
  return event.hook === "input.before" ? event.input : (event as { output?: unknown }).output;
}

function answer(does: Record<string, string>, event: HookEvent): unknown {
  switch (does.outcome) {
    case "continue":
      return { kind: "continue" };
    case "modify":
      return { kind: "continue", modified: eventOf(event.hook, does.value) };
    case "retry":
    case "escalate":
    case "suspend":
      return { kind: does.outcome, reason: does.reason };
    case "block":
      return { kind: "block", reason: does.reason, code: does.code };
    case "bad_answer":
      return "yes";
    case "bad_modify":
      return { kind: "continue", modified: eventOf(event.hook === "output.before" ? "input.before" : "output.before", "x") };
    default:
      throw new Error(`unknown behavior ${does.outcome}`);
  }
}

describe("bus", () => {
  it.each(casesOf("bus"))("%s", async (_, c) => {
    const hook = c.hook as HookPoint;
    const ran: string[] = [];
    const seen: Record<string, unknown> = {};
    const registrations: Registration[] = c.middleware.map((spec: Record<string, any>) => ({
      name: spec.name,
      hooks: new Set([hook]),
      band: spec.band,
      failMode: spec.fail_mode,
      ...(spec.does.outcome === "timeout" ? { timeout: 10 } : {}),
      handler: async (event: HookEvent) => {
        ran.push(spec.name);
        seen[spec.name] = valueOf(event);
        if (spec.does.outcome === "raise") throw new Error("scripted failure");
        if (spec.does.outcome === "timeout") await new Promise(() => {});
        return answer(spec.does, event) as Outcome;
      },
    }));
    if ("error" in c.expect) {
      let caught: unknown;
      try {
        new HookBus(registrations);
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(SpecError);
      expect((caught as SpecError).code).toBe(c.expect.error);
      return;
    }
    const bus = new HookBus(registrations);
    const clock = new FakeClock();
    const trace = new RunTrace(clock);
    const env = newEnvelope({ tenant: "t", principal: "p", clock });
    const result = await bus.emit(hook, eventOf(hook, c.value) as never, env, trace);
    const want = c.expect.outcome;
    expect(result.outcome.kind).toBe(want.kind);
    if ("modified" in want) {
      expect(result.outcome.kind).toBe("continue");
      expect((result.outcome as { modified?: unknown }).modified != null).toBe(want.modified);
    }
    if ("reason" in want) expect((result.outcome as { reason?: string }).reason).toBe(want.reason);
    if ("code" in want) expect((result.outcome as { code?: string }).code).toBe(want.code);
    expect(ran).toEqual(c.expect.ran);
    for (const [name, value] of Object.entries(c.expect.seen ?? {})) expect(seen[name]).toStrictEqual(value);
    expect(valueOf(result.event)).toStrictEqual(c.expect.value);
    const recorded = trace.events
      .filter((e) => e.kind === "outcome" || e.kind === "failure")
      .map((e) => [e.source, e.kind, e.outcome ?? null, e.modified]);
    expect(recorded).toEqual(c.expect.trace);
    const hooks = trace.events.filter((e) => e.kind === "hook");
    expect(hooks).toHaveLength(1);
    expect(hooks[0]!.outcome).toBe(want.kind);
  });
});

// --- budgets ---------------------------------------------------------------------------

describe("budgets", () => {
  it.each(casesOf("budgets"))("%s", (_, c) => {
    const want = c.expect;
    if ("cost" in c) {
      const given = c.cost;
      const prices = new Map<string, [number, number]>(Object.entries(given.prices));
      const request: ModelRequest = { messages: [{ role: "user", content: "x" }], ...given.request };
      const [usd, source] = resolveCost(given.response, request, prices.size ? (m) => prices.get(m) : undefined);
      expect(source).toBe(want.source);
      if (want.usd === null) expect(usd).toBeNull();
      else expect(usd).toBeCloseTo(want.usd, 12);
      return;
    }
    const meter = new BudgetMeter({ ...c.limits, deadline: null });
    const results: (string | null)[] = [];
    for (const op of c.ops) {
      let limit: string | undefined;
      if (op.op === "model.before") {
        limit = meter.checkModelCall({ messages: [{ role: "user", content: "a".repeat(op.chars) }] });
        if (limit === undefined) meter.startModelCall();
      } else if (op.op === "model.after") {
        limit = meter.recordModelCall(op.usage, op.cost_usd);
      } else {
        limit = meter.checkToolCall();
        if (limit === undefined) meter.startToolCall();
      }
      results.push(limit ?? null);
    }
    expect(results).toEqual(want.results);
    const m = want.meter;
    expect(meter.usd).toBeCloseTo(m.usd, 12);
    expect(meter.costKnown).toBe(m.cost_known);
    expect(meter.usage.input_tokens).toBe(m.input_tokens);
    expect(meter.usage.output_tokens).toBe(m.output_tokens);
    expect(meter.modelCalls).toBe(m.model_calls);
    expect(meter.toolCalls).toBe(m.tool_calls);
    if ("remaining" in want) {
      const left = meter.remaining() as Record<string, unknown>;
      for (const [key, value] of Object.entries(want.remaining)) {
        if (value === null) expect(left[key]).toBeNull();
        else expect(left[key]).toBeCloseTo(value as number);
      }
    }
  });
});

// --- plugins ---------------------------------------------------------------------------

describe("plugins", () => {
  it.each(casesOf("plugins"))("%s", (_, c) => {
    if ("owner_of" in c) expect(ownerOf(c.owner_of)).toBe(c.expect);
    else if ("qualify" in c) expect(qualify(c.qualify[0], c.qualify[1])).toBe(c.expect);
    else if ("owns" in c) expect(ownershipProblem(c.owns[0], c.owns[1]) === undefined).toBe(c.expect);
    else if ("allowed" in c) expect(isAllowed(c.allowed[0], c.allowed[1])).toBe(c.expect);
    else {
      let valid = true;
      try {
        checkNamespace(c.namespace);
      } catch {
        valid = false;
      }
      expect(valid).toBe(c.expect);
    }
  });
});
