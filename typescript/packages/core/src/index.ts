/**
 * `@harnessweaver/core`: the HarnessWeaver core for TypeScript. The same `harness.yaml`
 * as Python, with the same hook bus, guards, governor, routing, cel-lite and budgets,
 * held to the same language-neutral fixtures (R11).
 *
 *     import { load } from "@harnessweaver/core";
 *     const harness = load("harness.yaml");
 *     const answer = await harness.session({ task: "support", principal: user.id, tenant: user.org }, async (s) => {
 *       const route = await s.decide("intent", { text: question });
 *       ...
 *       return s.validate("output", reply);
 *     });
 *
 * This module is the public API (RULES C7); anything not exported here may change.
 */

export { Harness, load, type HarnessOptions, type LoadOptions, type SessionOptions, type ToolHandler } from "./harness.js";
export { ContextSource, Session, type DecideOptions } from "./session.js";
export { RunContext, MODEL_RETRIES, type ModelCall, type RunParts, type ToolBackend } from "./runtime.js";
export { currentRun, withRun, type RunScope } from "./current.js";

export { definePlugin, Registry, type Plugin, type PluginOptions } from "./plugins/plugin.js";
export { buildProvider, defineProvider, type Port, type ProviderDef, type ProviderOptions } from "./plugins/provider.js";
export { CONTRACT_VERSION, isAllowed, namespaceOf, ownerOf, qualify } from "./plugins/names.js";
export { defineMiddleware, type FailMode, type Handler, type MiddlewareDef, type MiddlewareOptions, type Registration } from "./middleware.js";

export { HookBus, halted, type HookResult } from "./bus.js";
export { BANDS, bandRank, directionOf, executionOrder, HOOK_POINTS, type Band, type EventOf, type HookEvent, type HookPoint } from "./hooks.js";
export { mostSevere, outcome, severity, type Block, type Continue, type Escalate, type Outcome, type OutcomeKind, type Retry, type Suspend } from "./outcomes.js";
export { RunTrace } from "./trace.js";
export { FakeClock, SystemClock, isWeekend, type Clock } from "./clock.js";
export { envelopeJson, newEnvelope, principalOf, withLabels, type Envelope, type EnvelopeOptions } from "./envelope.js";
export { BudgetMeter, estimateTokens, intersectBudgets, resolveCost, type Limit, type PriceLookup } from "./budgets.js";
export * from "./errors.js";
export type * from "./contracts.js";
export type { JsonObject, JsonValue } from "./json.js";

export { compileExpression, Expression, toHost, type Value } from "./expr/index.js";
export { CelLitePolicy, decideByRules, policyVariables, tighten, type PolicyConfig, type PolicyDecision, type PolicyEffect, type PolicyEngine, type PolicyRequest, type PolicyRule } from "./policy.js";
export { canonicalDigest, canonicalJson, definitionDigest } from "./digests.js";
export { checkSchema, SchemaError, validate, withDefaults, type Schema } from "./jsonschema.js";
export { formatDuration, parseDuration } from "./durations.js";
export { Version, VersionRange } from "./semver.js";
export { cosine, hashingEmbedding, lexicalSimilarity, tokens } from "./text.js";

export { BUILTIN_GUARDS, GroundedCitations, InjectionHeuristic, LlmJudge, PiiRegex, RegexDeny, SecretsScan, SizeLimit, TopicDeny } from "./guards/providers.js";
export { guardHandler, STAGE_HOOKS, type Guard, type Stage } from "./guards/pipeline.js";
export type { Guardrail } from "./guards/common.js";
export { cascadeHandler, decideInCascade, LexicalDecider, RulesDecider, type Decider, type Stage as RouteStage } from "./routing.js";
export { ContextSources, MemoryContext, type ContextProvider } from "./context.js";
export { PromptStore } from "./prompts.js";
export { Governor, type GovernedRun, type ToolsSettings } from "./tools/governor.js";
export { describeManifest, parseManifest, parseRate, type ToolDescription, type ToolManifest } from "./tools/manifests.js";
export { buildGrader, compare, GRADERS, parseGraders, readDataset, sampled, shadowReport, summarize, type EvalDataset, type EvalSample, type Evaluator, type Grade } from "./evals.js";
export { RemoteGuardrail, SidecarClient, type Caller, type SidecarOptions } from "./sidecar.js";

export { assess, LEVELS, type Level, type LevelReport } from "./spec/levels.js";
export { API_VERSION, EffectiveSpec, loadSpec, specFromDocuments, validateSpec, type HarnessSpec } from "./spec/loader.js";
export { mergeLayers, type Layer, type LayerKind, type Provenance } from "./spec/merge.js";
export { BuiltinProfiles, PluginProfiles, ProfileDirectories, type ProfileResolver } from "./spec/sources.js";
export { loadYaml } from "./spec/yaml.js";
