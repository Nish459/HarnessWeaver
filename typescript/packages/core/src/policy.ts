/**
 * Policy: deterministic allow, deny or require-approval (DESIGNS No. 17, ADR-0025, R3).
 *
 * Every engine combines `policy.rules` the same way: among rules whose `when` is true,
 * deny beats require_approval beats allow, and the first of equals decides; a `when`
 * that can't be evaluated never loosens (deny and approval rules count as matching,
 * allow rules don't); with no match, `default_effect` decides a tool call, while a run
 * is only restricted by its own rules.
 */

import type { Labels, Principal, ToolInfo } from "./contracts.js";
import { ExpressionEvalError, ExpressionSyntaxError, SpecError } from "./errors.js";
import { compileExpression, type Expression } from "./expr/index.js";
import type { JsonObject } from "./json.js";
import { defineProvider } from "./plugins/provider.js";

export type PolicyEffect = "allow" | "require_approval" | "deny";
export type PolicyHook = "tool.before" | "run.start";

const RANK: Record<PolicyEffect, number> = { allow: 0, require_approval: 1, deny: 2 };

/** Combine an effect with a check that may only make it stricter (R3). */
export function tighten(current: PolicyEffect, proposed: PolicyEffect): PolicyEffect {
  return RANK[proposed] > RANK[current] ? proposed : current;
}

export const TOOL_POLICY_VARIABLES = ["principal", "tenant", "task", "tool", "args", "labels"];
export const RUN_POLICY_VARIABLES = ["principal", "tenant", "task", "labels"];

export interface PolicyRule {
  id?: string | null;
  when: string;
  effect: PolicyEffect;
  reason?: string | null;
  hook?: PolicyHook;
}

export interface PolicyConfig {
  rules?: PolicyRule[];
  default_effect?: PolicyEffect;
}

/** What a policy engine is asked (schema `policy-request`). */
export interface PolicyRequest {
  hook?: PolicyHook;
  principal: Principal;
  tenant: string;
  task?: string | null;
  task_version?: string | null;
  tool?: ToolInfo | null;
  args?: JsonObject | null;
  labels?: Labels;
}

export interface PolicyDecision {
  effect: PolicyEffect;
  rule?: string | null;
  reason?: string | null;
}

/** The port every policy engine implements; providers must be deterministic (R3). */
export interface PolicyEngine {
  decide(request: PolicyRequest): Promise<PolicyDecision> | PolicyDecision;
}

/** The names a rule's `when` sees, as plain JSON values with the contract's defaults. */
export function policyVariables(request: PolicyRequest): Record<string, unknown> {
  const variables: Record<string, unknown> = {
    principal: { roles: [], attrs: {}, ...request.principal },
    tenant: request.tenant,
    task: { name: request.task ?? null, version: request.task_version ?? null },
    labels: { data_class: null, untrusted_seen: false, private_seen: false, sources: [], ...request.labels },
  };
  if ((request.hook ?? "tool.before") === "tool.before") {
    variables.tool = request.tool
      ? { version: null, side_effect: "none", risk: "low", egress: [], data_access: [], scopes: [], ...request.tool }
      : null;
    variables.args = request.args ?? {};
  }
  return variables;
}

/**
 * Combine `rules` as every engine must (see the module docs). `matches` evaluates one
 * rule: true, false, or undefined when it can't be evaluated.
 */
export function decideByRules(
  rules: readonly PolicyRule[],
  defaultEffect: PolicyEffect,
  hook: PolicyHook,
  matches: (rule: PolicyRule) => boolean | undefined,
): PolicyDecision {
  let best: PolicyDecision | undefined;
  rules.forEach((rule, index) => {
    if ((rule.hook ?? "tool.before") !== hook) return;
    const label = rule.id || `rule#${index + 1}`;
    const matched = matches(rule);
    let reason: string;
    if (matched === undefined) {
      if (rule.effect === "allow") return;
      reason = `policy rule ${label} couldn't be checked`;
    } else if (!matched) {
      return;
    } else {
      reason = rule.reason || `policy rule ${label}`;
    }
    if (best === undefined || RANK[rule.effect] > RANK[best.effect]) best = { effect: rule.effect, rule: label, reason };
  });
  if (best !== undefined) return best;
  const effect = hook === "tool.before" ? defaultEffect : "allow";
  return { effect, rule: null, reason: `no policy rule matched; default ${effect}` };
}

/** `cel_lite`: rules in cel-lite, compiled at load so a typo fails then (R4). */
export class CelLitePolicy implements PolicyEngine {
  private readonly compiled = new Map<PolicyRule, Expression>();
  private readonly rules: PolicyRule[];
  private readonly defaultEffect: PolicyEffect;

  /** @throws SpecError for a rule that doesn't compile. */
  constructor(config: PolicyConfig = {}) {
    this.rules = config.rules ?? [];
    this.defaultEffect = config.default_effect ?? "allow";
    this.rules.forEach((rule, index) => {
      const names = (rule.hook ?? "tool.before") === "tool.before" ? TOOL_POLICY_VARIABLES : RUN_POLICY_VARIABLES;
      try {
        this.compiled.set(rule, compileExpression(rule.when, names));
      } catch (error) {
        if (error instanceof ExpressionSyntaxError) throw new SpecError(`policy.rules[${rule.id ?? index}].when: ${error.message}`);
        throw error;
      }
    });
  }

  decide(request: PolicyRequest): PolicyDecision {
    const variables = policyVariables(request);
    return decideByRules(this.rules, this.defaultEffect, request.hook ?? "tool.before", (rule) => {
      try {
        return this.compiled.get(rule)!.evaluateBool(variables);
      } catch (error) {
        if (error instanceof ExpressionEvalError) return undefined;
        throw error;
      }
    });
  }
}

const EFFECT = { enum: ["allow", "require_approval", "deny"] };

export const celLitePolicy = defineProvider({
  port: "PolicyEngine",
  name: "cel_lite",
  deterministic: true,
  settings: {
    properties: {
      rules: {
        type: "array",
        default: [],
        items: {
          type: "object",
          additionalProperties: false,
          required: ["when", "effect"],
          properties: {
            id: { anyOf: [{ type: "string" }, { type: "null" }] },
            when: { type: "string" },
            effect: EFFECT,
            reason: { anyOf: [{ type: "string" }, { type: "null" }] },
            hook: { enum: ["tool.before", "run.start"] },
          },
        },
      },
      default_effect: { ...EFFECT, default: "allow" },
    },
  },
  create: (s) => new CelLitePolicy(s as PolicyConfig),
});
