/**
 * The TypeScript harness: one effective spec, built into a hook bus and the modules
 * TypeScript runs natively (guards, validation rules, middleware, routing, policy, the
 * tool governor, context, prompts), and sessions that run on it (DESIGNS No. 24).
 *
 * TypeScript doesn't run tasks or call models itself: the app's flow is the session,
 * and its model calls go through `wrapModel`. So `tasks.*.runner` and `models.provider`
 * are left to Python, while every control TypeScript is asked to enforce must be one it
 * can: an unknown guard, stage, policy engine or context provider fails loading (R4),
 * unless a guard is declared `where: sidecar`.
 */

import { globSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import type { PriceLookup } from "./budgets.js";
import { intersectBudgets } from "./budgets.js";
import { HookBus } from "./bus.js";
import { SystemClock, isoTime, type Clock } from "./clock.js";
import { ContextSources, type ContextProvider, type ContextSourceSettings } from "./context.js";
import type { Budget, RunResult, RunStatus } from "./contracts.js";
import { withRun } from "./current.js";
import { newEnvelope, type Envelope } from "./envelope.js";
import { classify, ExpressionError, RunBlocked, RunInterrupted, SpecError, ToolError } from "./errors.js";
import { compileExpression } from "./expr/index.js";
import type { Guardrail } from "./guards/common.js";
import { guardHandler, STAGE_HOOKS, type Guard, type Stage } from "./guards/pipeline.js";
import { HOOK_POINTS, type Band } from "./hooks.js";
import { parseDuration } from "./durations.js";
import { isObject, type JsonObject, type JsonValue } from "./json.js";
import type { FailMode } from "./middleware.js";
import { isAllowed, ownerOf } from "./plugins/names.js";
import { Registry, type Plugin } from "./plugins/plugin.js";
import { buildProvider } from "./plugins/provider.js";
import type { PolicyEngine } from "./policy.js";
import { PromptStore } from "./prompts.js";
import { cascadeHandler, type Decider, type Stage as RouteStage } from "./routing.js";
import { RunContext, type ToolBackend } from "./runtime.js";
import { Session } from "./session.js";
import { RemoteGuardrail, SidecarClient } from "./sidecar.js";
import { budgetOf, loadSpec, type EffectiveSpec, type LoadOptions as SpecLoadOptions } from "./spec/loader.js";
import type { LayerKind, RawMap } from "./spec/merge.js";
import { PluginProfiles } from "./spec/sources.js";
import { loadYamlFile } from "./spec/yaml.js";
import { Governor } from "./tools/governor.js";
import { approvalRules, describeManifest, parseManifest, type ToolDescription, type ToolManifest } from "./tools/manifests.js";

/** A tool given in code: called with the arguments, returns JSON. */
export type ToolHandler = (args: JsonObject, env: Envelope) => Promise<JsonValue> | JsonValue;

export interface HarnessOptions {
  /** Plugins the spec may use (`definePlugin`). */
  plugins?: readonly Plugin[];
  /** Tool handlers, by tool name; each tool still needs its manifest (S2). */
  tools?: Readonly<Record<string, ToolHandler>>;
  clock?: Clock;
  /** How `where: sidecar` guards reach harnessd; defaults to `sidecar.url` from the spec. */
  sidecar?: SidecarClient;
}

export interface LoadOptions extends HarnessOptions, Omit<SpecLoadOptions, "extraResolvers"> {}

export interface SessionOptions {
  task?: string | null;
  principal?: string | { id: string; roles?: string[]; attrs?: JsonObject };
  tenant?: string;
  /** May only tighten the spec's limits; `deadline` in milliseconds. */
  budget?: Budget;
  attributes?: Record<string, string>;
  input?: JsonValue;
  /** Told the run's result when the session ends, completed or not. */
  onEnd?: (result: RunResult) => void;
}

const LAYER_BANDS: Record<LayerKind, Band> = { org: "baseline", defaults: "platform", profile: "platform", app: "app", overlay: "app" };
const map = (value: unknown): RawMap => (isObject(value) ? value : {});
const list = (value: unknown): RawMap[] => (Array.isArray(value) ? value.filter(isObject) : []);

/** The settings a section's entry gives its provider: everything but the section's own keys. */
function settingsOf(entry: RawMap, own: readonly string[]): JsonObject {
  return Object.fromEntries(Object.entries(entry).filter(([key]) => !own.includes(key))) as JsonObject;
}

const GUARD_KEYS = ["id", "use", "action", "mode", "where", "parallel", "fail_mode", "timeout", "enabled"];

/** The harness for one effective spec. */
export class Harness {
  private constructor(
    readonly spec: EffectiveSpec,
    readonly bus: HookBus,
    readonly registry: Registry,
    private readonly parts: {
      clock: Clock;
      tools: ToolBackend;
      governor: Governor;
      policy: PolicyEngine;
      context: ContextSources;
      prompts: PromptStore;
      prices: PriceLookup | undefined;
      allowedModels: ReadonlySet<string> | null;
    },
  ) {}

  get name(): string {
    return this.spec.spec.metadata.name;
  }

  /**
   * Build a harness from a loaded spec.
   *
   * @throws SpecError for anything the spec asks TypeScript to enforce that it can't.
   */
  static fromSpec(effective: EffectiveSpec, options: HarnessOptions = {}): Harness {
    const spec = effective.spec;
    const base = effective.path ? dirname(effective.path) : process.cwd();
    const relative = (path: string): string => (isAbsolute(path) ? path : join(base, path));
    const plugins = map(spec.plugins);
    const registry = new Registry(options.plugins ?? [], (plugins.allow as string[] | null | undefined) ?? null);
    const sidecarSpec = map(spec.sidecar);
    const sidecar =
      options.sidecar ??
      (typeof sidecarSpec.url === "string" ? new SidecarClient({ url: sidecarSpec.url, tokenEnv: (sidecarSpec.token_env as string | undefined) ?? "HARNESSD_TOKEN" }) : undefined);
    const bus = new HookBus();
    installGuards(effective, registry, bus, sidecar, plugins.allow as string[] | null | undefined);
    installValidation(effective, bus);
    installMiddleware(spec, registry, bus);
    installRouting(effective, registry, bus, relative);

    const policySpec = map(spec.policy);
    const policy = buildProvider<PolicyEngine>(registry.provider("PolicyEngine", String(policySpec.use ?? "cel_lite")), {
      ...settingsOf(policySpec, ["use", "rules", "default_effect"]),
      rules: (policySpec.rules ?? []) as JsonValue,
      default_effect: (policySpec.default_effect ?? "allow") as JsonValue,
    });

    const toolsSpec = map(spec.tools);
    const manifests = (Array.isArray(toolsSpec.manifests) ? (toolsSpec.manifests as string[]) : []).flatMap((pattern) => {
      const found = globSync(pattern, { cwd: base }).sort();
      if (found.length === 0) throw new SpecError(`tools.manifests: '${pattern}' matches no file`);
      return found.map((file) => parseManifest(loadYamlFile(join(base, file)), join(base, file)));
    });
    const tools = codeTools(manifests, options.tools ?? {});
    const judgeSpec = isObject(toolsSpec.judge) ? toolsSpec.judge : undefined;
    const judge = judgeSpec ? buildProvider<Guardrail>(registry.provider("Guardrail", String(judgeSpec.use)), settingsOf(judgeSpec, ["use"])) : undefined;
    const taskApprovals = Object.fromEntries(Object.entries(map(spec.tasks)).map(([name, task]) => [name, ((map(map(task).approvals).tools as string[]) ?? [])]));
    const governor = new Governor({ policy, tools: toolsSpec, approvalRules: approvalRules(manifests), taskApprovals, ...(judge ? { judge } : {}) });

    const sources = new Map<string, [ContextSourceSettings, ContextProvider]>();
    for (const [name, entry] of Object.entries(map(spec.context))) {
      const settings = settingsOf(map(entry), ["use", "label", "max_items", "max_tokens", "require_acl"]);
      if (typeof settings.file === "string") settings.file = relative(settings.file);
      const provider = buildProvider<ContextProvider>(registry.provider("ContextProvider", String(map(entry).use)), settings);
      sources.set(name, [map(entry) as ContextSourceSettings, provider]);
    }

    const models = map(spec.models);
    const prices = new Map(Object.entries(map(models.prices)).map(([name, price]) => [name, [Number(map(price).input_per_mtok), Number(map(price).output_per_mtok)] as const]));
    const aliases = map(models.aliases) as Record<string, string>;
    const allowed = Array.isArray(models.allowed_aliases) ? new Set((models.allowed_aliases as string[]).flatMap((a) => [a, aliases[a] ?? a])) : null;

    return new Harness(effective, bus, registry, {
      clock: options.clock ?? new SystemClock(),
      tools,
      governor,
      policy,
      context: new ContextSources(sources),
      prompts: new PromptStore(relative(String(map(spec.prompts).dir ?? "prompts"))),
      prices: prices.size ? (model) => prices.get(model) : undefined,
      allowedModels: allowed,
    });
  }

  /** The middleware names on every hook point, in run order. */
  hooks(task?: string | null): Record<string, string[]> {
    return Object.fromEntries(HOOK_POINTS.map((hook) => [hook, this.bus.chain(hook, task).map((r) => r.name)]));
  }

  /**
   * Run `fn` as a governed session: `run.start` (and its policy rules), the app's flow,
   * then `run.end`. Returns what `fn` returns; a halting outcome throws in `fn`.
   */
  async session<T>(options: SessionOptions, fn: (session: Session) => Promise<T> | T): Promise<T> {
    const task = options.task ?? null;
    const tasks = map(this.spec.spec.tasks);
    let limits = task !== null && task in tasks ? this.spec.runBudget(task) : budgetOf(map(this.spec.spec.budgets).per_run);
    if (options.budget) limits = intersectBudgets(limits, options.budget);
    const envelope = newEnvelope({
      tenant: options.tenant ?? "default",
      principal: options.principal ?? "anonymous",
      task,
      task_version: task !== null ? ((map(tasks[task]).version as string | undefined) ?? null) : null,
      budget: limits,
      clock: this.parts.clock,
      attributes: options.attributes ?? {},
    });
    const run = new RunContext({
      bus: this.bus,
      envelope,
      task,
      input: options.input ?? null,
      tools: this.parts.tools,
      governor: this.parts.governor,
      policy: this.parts.policy,
      context: this.parts.context,
      prompts: this.parts.prompts,
      ...(this.parts.prices ? { prices: this.parts.prices } : {}),
      allowedModels: this.parts.allowedModels,
    });
    const started = this.parts.clock.now();
    return withRun(run, async () => {
      try {
        run.haltOn(await run.emit("run.start", { hook: "run.start", task, input: options.input ?? null }));
        await run.authorizeRun();
        const value = await fn(new Session(run));
        await this.finish(run, "completed", null, started, options.onEnd);
        return value;
      } catch (error) {
        const status: RunStatus = error instanceof RunBlocked ? "blocked" : error instanceof RunInterrupted ? "escalated" : "failed";
        await this.finish(run, status, error, started, options.onEnd);
        throw error;
      }
    });
  }

  private async finish(run: RunContext, status: RunStatus, error: unknown, started: number, onEnd?: (result: RunResult) => void): Promise<void> {
    const info = error === null ? null : classify(error).toInfo();
    const usage = { ...run.meter.usage };
    if (info !== null && status === "failed") await run.emit("run.error", { hook: "run.error", error: info, step: null }, false);
    await run.emit("run.end", { hook: "run.end", status, output: run.output, error: info, usage, cost_usd: run.meter.costKnown ? run.meter.usd : null }, false);
    onEnd?.({
      run_id: run.runId,
      task: run.task,
      task_version: run.envelope.task_version ?? null,
      status,
      output: run.output,
      error: info,
      approval: null,
      usage,
      cost_usd: run.meter.costKnown ? run.meter.usd : null,
      cost_known: run.meter.costKnown,
      trace: [...run.trace.events],
      started_at: isoTime(started),
      ended_at: isoTime(this.parts.clock.now()),
    });
  }
}

/** Load `harness.yaml` (profiles, overlay, plugins' profiles) and build its harness. */
export function load(path: string, options: LoadOptions = {}): Harness {
  const plugins = options.plugins ?? [];
  const effective = loadSpec(path, { ...options, extraResolvers: [new PluginProfiles(plugins)] });
  return Harness.fromSpec(effective, options);
}

/** Tools given in code, described by their manifests (S2); tools with no manifest have none. */
function codeTools(manifests: readonly ToolManifest[], handlers: Readonly<Record<string, ToolHandler>>): ToolBackend {
  const described = new Map<string, ToolDescription>(manifests.map((m) => [m.metadata.name, describeManifest(m)]));
  for (const name of Object.keys(handlers)) if (!described.has(name)) described.set(name, { info: { name }, spec: { name }, manifest: null, digestOk: true });
  return {
    describe: (name) => described.get(name),
    execute: async (call, env) => {
      const handler = handlers[call.name];
      if (handler === undefined) throw new ToolError(`tool ${call.name} has no handler in TypeScript; pass it to load({ tools })`);
      return { call_id: call.id, output: (await handler(call.arguments ?? {}, env)) ?? null, is_error: false, untrusted: true, truncated: false };
    },
  };
}

function bandOf(effective: EffectiveSpec, path: string, fallback: Band = "app"): Band {
  const origin = effective.origin(`${path}.id`) ?? effective.origin(`${path}.use`) ?? effective.origin(`${path}.when`) ?? effective.origin(path);
  return origin ? LAYER_BANDS[origin.kind] : fallback;
}

/** Turn every enabled guard into middleware, banded by the layer that declared it (No. 20). */
function installGuards(effective: EffectiveSpec, registry: Registry, bus: HookBus, sidecar: SidecarClient | undefined, allow: readonly string[] | null | undefined): void {
  const spec = effective.spec;
  const sections: [string | null, string, RawMap][] = [[null, "guardrails", map(spec.guardrails)]];
  for (const [name, task] of Object.entries(map(spec.tasks))) if (isObject(map(task).guardrails)) sections.push([name, `tasks.${name}.guardrails`, map(map(task).guardrails)]);
  for (const [task, prefix, section] of sections) {
    for (const stage of Object.keys(STAGE_HOOKS) as Stage[]) {
      const items = list(section[stage]).filter((item) => item.enabled !== false);
      const groups: [RawMap, Band][][] = [];
      for (const item of items) {
        const band = task !== null ? "task" : bandOf(effective, `${prefix}.${stage}[${String(item.id)}]`);
        const last = groups.at(-1);
        if (item.parallel && last && last.at(-1)![0].parallel && last.at(-1)![1] === band) last.push([item, band]);
        else groups.push([[item, band]]);
        // Each guard, not each group: a parallel group's own fail mode is closed if any
        // member's is, while each member still fails its own way (R2).
        if (band === "baseline" && item.fail_mode === "open") {
          throw new SpecError(`guard ${prefix}.${stage}[${String(item.id)}] is in the baseline band but fails open; baseline guards must fail closed (RULES R2)`);
        }
      }
      for (const group of groups) {
        const guards = group.map(([item]) => guardOf(item, items.indexOf(item), stage, prefix, registry, sidecar, allow));
        const label = `${prefix}.${stage}[${guards.map((g) => g.id).join("+")}]`;
        const closed = guards.some((g) => g.failMode !== "open");
        bus.add({
          name: label,
          handler: guardHandler(stage, guards, label),
          hooks: new Set([STAGE_HOOKS[stage]]),
          band: group[0]![1],
          failMode: guards.length === 1 ? (guards[0]!.failMode ?? "closed") : closed ? "closed" : "open",
          ...(guards.length === 1 && guards[0]!.timeout ? { timeout: guards[0]!.timeout } : {}),
          ...(task !== null ? { tasks: new Set([task]) } : {}),
        });
      }
    }
  }
}

function guardOf(item: RawMap, index: number, stage: Stage, prefix: string, registry: Registry, sidecar: SidecarClient | undefined, allow: readonly string[] | null | undefined): Guard {
  const use = String(item.use);
  const id = String(item.id ?? `${use}#${index + 1}`);
  let provider: Guardrail;
  const settings = settingsOf(item, GUARD_KEYS);
  if ((item.where ?? "local") === "sidecar") {
    if (sidecar === undefined) throw new SpecError(`guard ${id}: where: sidecar needs sidecar.url`);
    if (!isAllowed(ownerOf(use), allow)) throw new SpecError(`plugin namespace '${ownerOf(use)}' isn't in plugins.allow`);
    provider = new RemoteGuardrail(sidecar, use, settings, stage);
  } else {
    const def = registry.provider<Guardrail>("Guardrail", use);
    if (def.stages.length && !def.stages.includes(stage)) throw new SpecError(`guard ${use} can't run at stage '${stage}'; it supports ${def.stages.join(", ")}`);
    provider = buildProvider(def, settings);
  }
  return {
    id,
    name: `${prefix}.${stage}[${id}]`,
    provider,
    action: (item.action as Guard["action"]) ?? null,
    mode: (item.mode as Guard["mode"]) ?? "enforce",
    failMode: (item.fail_mode as FailMode | undefined) ?? "closed",
    timeout: item.timeout === null || item.timeout === undefined ? null : parseDuration(item.timeout),
  };
}

/** `validation.rules` as `output.before` middleware: a true (or unevaluable) `when` asks for a repair. */
function installValidation(effective: EffectiveSpec, bus: HookBus): void {
  list(map(effective.spec.validation).rules).forEach((rule, index) => {
    const label = String(rule.id ?? index);
    const expression = compileExpression(String(rule.when), ["output", "input", "task"]);
    const message = String(rule.message);
    bus.add({
      name: `validation.rules[${label}]`,
      hooks: new Set(["output.before"]),
      band: bandOf(effective, `validation.rules[${label}]`),
      failMode: "closed",
      handler: (event, env) => {
        if (event.hook !== "output.before") return undefined;
        try {
          const violated = expression.evaluateBool({ output: event.output, input: null, task: { name: env.task ?? null, version: env.task_version ?? null } });
          return violated ? { kind: "retry", reason: message } : undefined;
        } catch (error) {
          if (error instanceof ExpressionError) return { kind: "retry", reason: `${message} (the rule couldn't be checked)` };
          throw error;
        }
      },
    });
  });
}

/** The spec's `middleware:` entries, from registered plugins. */
function installMiddleware(spec: RawMap, registry: Registry, bus: HookBus): void {
  const items = list(spec.middleware);
  const uses = items.map((item) => String(item.use));
  for (const item of items) {
    if (item.enabled === false) continue;
    const use = String(item.use);
    const declared = registry.middleware(use);
    const hooks = Array.isArray(item.hooks) ? (item.hooks as string[]) : [...declared.hooks];
    const extra = hooks.filter((h) => !declared.hooks.includes(h as never));
    if (extra.length) throw new SpecError(`middleware[${String(item.id)}].hooks: ${use} doesn't attach to ${extra.join(", ")}; it declares ${declared.hooks.join(", ")}`);
    bus.add({
      name: uses.filter((u) => u === use).length > 1 && item.id ? `${use}[${String(item.id)}]` : use,
      handler: declared.build(settingsOf(item, ["id", "use", "band", "hooks", "fail_mode", "timeout", "enabled"])),
      hooks: new Set(hooks as never[]),
      band: (item.band as Band | undefined) ?? declared.band,
      failMode: (item.fail_mode as FailMode | undefined) ?? declared.failMode,
      ...(declared.timeout !== undefined ? { timeout: declared.timeout } : {}),
    });
  }
}

/** One cascade per `routing.<router>`, its stages from the registry (rules, lexical, plugins). */
function installRouting(effective: EffectiveSpec, registry: Registry, bus: HookBus, relative: (path: string) => string): void {
  for (const [name, raw] of Object.entries(map(effective.spec.routing))) {
    const router = map(raw);
    const options = (router.options as string[] | undefined) ?? [];
    const stages: RouteStage[] = list(router.cascade).map((item, index) => {
      const where = `routing.${name}.cascade[${String(item.id ?? index)}]`;
      const settings = settingsOf(item, ["id", "use", "threshold"]);
      if (typeof settings.file === "string") settings.file = relative(settings.file);
      let decider: { decide: Decider; choices?: Set<string> };
      try {
        decider = buildProvider(registry.provider<{ decide: Decider; choices?: Set<string> }>("Decider", String(item.use)), settings);
      } catch (error) {
        if (error instanceof SpecError) throw new SpecError(`${where}: ${error.message}`);
        throw error;
      }
      const unknown = [...(decider.choices ?? [])].filter((c) => !options.includes(c)).sort();
      if (unknown.length) throw new SpecError(`${where}: ${unknown.join(", ")} isn't one of the router's options`);
      return { label: String(item.id ?? item.use), decider: decider.decide, threshold: (item.threshold as number | null | undefined) ?? null };
    });
    bus.add({
      name: `routing.${name}`,
      handler: cascadeHandler(name, options, (router.default as string | null | undefined) ?? null, stages),
      hooks: new Set(["route.decide"]),
      band: bandOf(effective, `routing.${name}.options`),
      failMode: "closed",
    });
  }
}
