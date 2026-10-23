/**
 * The tool governor: deterministic steps around every tool call (DESIGNS No. 17,
 * fixtures suite `governor`). Steps 1 to 7 run in `authorize`, on the call's final
 * arguments after the `tool.before` middleware (ADR-0025); step 9 is `sanitize`.
 * Every decision is a `harness.governor` trace note with its step and reason (R13).
 *
 * 1. Registry: a manifest (when required), enabled for the tenant, its pin matching (S2).
 * 2. Schema: the arguments match `input_schema`.
 * 3. Policy: the engine (deny blocks), plus the approvals the manifest, the risk rules
 *    and the task ask for.
 * 4. Lethal trifecta: untrusted and private data and a tool with egress (S3).
 * 5. Limits: `rate_limit` per principal and per tenant, held under concurrency.
 * 6. Judge: `tools.judge` can only tighten (R3).
 * 7. Approval: a call that needs one suspends, unless a human already approved it.
 */

import type { Clock } from "../clock.js";
import { pythonJson } from "../digests.js";
import type { ApprovalDecision, ToolCall, ToolResult, ToolVerdict } from "../contracts.js";
import type { Envelope } from "../envelope.js";
import { ExpressionError } from "../errors.js";
import { compileExpression, type Expression } from "../expr/index.js";
import type { Guardrail } from "../guards/common.js";
import { validate } from "../jsonschema.js";
import type { OutcomeKind } from "../outcomes.js";
import { policyVariables, tighten, TOOL_POLICY_VARIABLES, type PolicyEffect, type PolicyEngine, type PolicyRequest } from "../policy.js";
import type { RunTrace } from "../trace.js";
import { limitKey, RateLimiter, type LimitKey, type Reservation } from "./limits.js";
import { parseRate, type OutputPolicy, type ToolDescription } from "./manifests.js";
import { sanitize } from "./sanitize.js";

const SOURCE = "harness.governor";
const OUTCOMES: Record<ToolVerdict["decision"], OutcomeKind> = { allow: "continue", require_approval: "suspend", block: "block" };

/** The `tools` section of a spec, as the governor reads it. */
export interface ToolsSettings {
  require_manifest?: boolean;
  max_output_bytes?: number;
  trifecta?: "require_approval" | "block";
  approval_by_risk?: Partial<Record<string, "required" | "none">>;
}

/** What the governor reads from a run. */
export interface GovernedRun {
  envelope: Envelope;
  trace: RunTrace;
  clock: Clock;
}

function block(step: number, code: string, reason: string): ToolVerdict {
  return { decision: "block", step, code, reason, approver_role: null };
}

export interface GovernorOptions {
  policy: PolicyEngine;
  tools?: ToolsSettings;
  approvalRules?: Map<string, Expression>;
  /** Tools each task always asks a person about (`approvals.tools`). */
  taskApprovals?: Record<string, readonly string[]>;
  judge?: Guardrail;
}

/** The built-in tool governor of one harness. */
export class Governor {
  readonly limiter = new RateLimiter();
  private readonly policy: PolicyEngine;
  readonly settings: ToolsSettings;
  private readonly approvalRules: Map<string, Expression>;
  private readonly taskApprovals: Record<string, readonly string[]>;
  private readonly judge: Guardrail | undefined;

  constructor(options: GovernorOptions) {
    this.policy = options.policy;
    this.settings = options.tools ?? {};
    this.approvalRules = new Map(options.approvalRules ?? []);
    this.taskApprovals = options.taskApprovals ?? {};
    this.judge = options.judge;
  }

  /** Steps 1 to 7 for one call, traced (R13). A dry run gives back the rate-limit place it took. */
  async authorize(run: GovernedRun, call: ToolCall, tool: ToolDescription, approval: ApprovalDecision | null, dryRun = false): Promise<ToolVerdict> {
    let reservation: Reservation | undefined;
    let verdict = this.registry(run, tool) ?? this.schema(call, tool);
    if (verdict === undefined) {
      const decided = await this.approvals(run, call, tool);
      let { effect } = decided;
      verdict = decided.verdict;
      if (verdict === undefined) [reservation, verdict] = this.limits(run, tool);
      if (verdict === undefined) [effect, verdict] = await this.judged(run, call, effect, decided.reasons);
      verdict ??= this.approval(effect, decided.role, decided.reasons, approval);
    }
    if (reservation !== undefined && (dryRun || verdict.decision !== "allow")) this.limiter.release(reservation);
    run.trace.note(SOURCE, verdict.reason, {
      hook: "tool.before",
      code: verdict.code ?? null,
      outcome: OUTCOMES[verdict.decision],
      details: { tool: call.name, step: verdict.step, decision: verdict.decision },
    });
    return verdict;
  }

  private registry(run: GovernedRun, tool: ToolDescription): ToolVerdict | undefined {
    const { name } = tool.info;
    const manifest = tool.manifest;
    if (!manifest) return (this.settings.require_manifest ?? true) ? block(1, "manifest_required", `tool ${name} has no manifest (S2)`) : undefined;
    if (!manifest.spec.enabled) return block(1, "tool_disabled", `tool ${name} is disabled`);
    const tenants = manifest.spec.tenants;
    if (tenants.length && !tenants.includes(run.envelope.tenant)) return block(1, "tool_not_enabled", `tool ${name} isn't enabled for this tenant`);
    if (!tool.digestOk) return block(1, "digest_mismatch", `tool ${name}'s definition doesn't match its pinned digest`);
    return undefined;
  }

  private schema(call: ToolCall, tool: ToolDescription): ToolVerdict | undefined {
    const problems = validate(call.arguments ?? {}, tool.spec.input_schema ?? { type: "object" });
    return problems.length ? block(2, "schema_invalid", `tool ${call.name} arguments: ${problems.join("; ")}`) : undefined;
  }

  /** Steps 3 and 4: the policy engine, the other approval sources, the trifecta. */
  private async approvals(
    run: GovernedRun,
    call: ToolCall,
    tool: ToolDescription,
  ): Promise<{ effect: PolicyEffect; role: string | null; reasons: string[]; verdict?: ToolVerdict }> {
    const envelope = run.envelope;
    const request: PolicyRequest = {
      principal: envelope.principal,
      tenant: envelope.tenant,
      task: envelope.task ?? null,
      task_version: envelope.task_version ?? null,
      tool: tool.info,
      args: call.arguments ?? {},
      labels: envelope.labels,
    };
    const decision = await this.policy.decide(request);
    if (decision.effect === "deny") {
      return { effect: "deny", role: null, reasons: [], verdict: block(3, "policy_denied", decision.reason || "the policy denies it") };
    }
    let effect: PolicyEffect = decision.effect;
    const reasons: string[] = [];
    if (effect === "require_approval") reasons.push(decision.reason || "the policy requires approval");
    const manifest = tool.manifest;
    const role = manifest?.spec.approval?.approver_role ?? null;
    const when = manifest?.spec.approval?.when;
    if (when) {
      let needed: boolean;
      try {
        needed = this.approvalRule(call.name, when).evaluateBool(policyVariables(request));
      } catch (error) {
        if (!(error instanceof ExpressionError)) throw error;
        needed = true; // can't tell: ask a person rather than let it through
      }
      if (needed) {
        effect = tighten(effect, "require_approval");
        reasons.push(`tool ${call.name}'s approval rule`);
      }
    }
    const risk = tool.info.risk ?? "low";
    if (this.settings.approval_by_risk?.[risk] === "required") {
      effect = tighten(effect, "require_approval");
      reasons.push(`${risk}-risk tools need approval`);
    }
    if ((this.taskApprovals[envelope.task ?? ""] ?? []).includes(call.name)) {
      effect = tighten(effect, "require_approval");
      reasons.push(`task ${envelope.task} asks before ${call.name}`);
    }
    const labels = envelope.labels;
    if (labels.untrusted_seen && labels.private_seen && (tool.info.egress ?? []).length) {
      const reason = `tool ${call.name} can send data out after untrusted and private data entered the run (lethal trifecta, S3)`;
      if (this.settings.trifecta === "block") return { effect, role, reasons, verdict: block(4, "trifecta", reason) };
      effect = tighten(effect, "require_approval");
      reasons.push(reason);
    }
    return { effect, role, reasons };
  }

  /** The tool's compiled `approval.when`: from load for manifest files, on first use otherwise. */
  private approvalRule(name: string, source: string): Expression {
    let rule = this.approvalRules.get(name);
    if (rule === undefined || rule.source !== source) {
      rule = compileExpression(source, TOOL_POLICY_VARIABLES);
      this.approvalRules.set(name, rule);
    }
    return rule;
  }

  private limits(run: GovernedRun, tool: ToolDescription): [Reservation | undefined, ToolVerdict | undefined] {
    const limit = tool.manifest?.spec.rate_limit;
    if (!limit) return [undefined, undefined];
    const name = tool.info.name;
    const wanted: [LimitKey, number, number][] = [];
    if (limit.per_principal) wanted.push([limitKey(name, "principal", run.envelope.principal.id), ...parseRate(limit.per_principal)]);
    if (limit.per_tenant) wanted.push([limitKey(name, "tenant", run.envelope.tenant), ...parseRate(limit.per_tenant)]);
    const reservation = this.limiter.acquire(wanted, run.clock.now() / 1000);
    return reservation === undefined ? [undefined, block(5, "rate_limited", `tool ${name} is over its rate limit`)] : [reservation, undefined];
  }

  private async judged(run: GovernedRun, call: ToolCall, effect: PolicyEffect, reasons: string[]): Promise<[PolicyEffect, ToolVerdict | undefined]> {
    if (this.judge === undefined) return [effect, undefined];
    // The same text Python's governor gives the judge, so a pattern-matching judge agrees.
    const content = pythonJson({ tool: call.name, args: call.arguments ?? {} });
    try {
      const judged = await this.judge.check(content, run.envelope);
      if (judged.action === "block") return ["deny", block(6, "judge_blocked", judged.reason || "the judge blocks it")];
      if (judged.action === "require_approval" || judged.action === "escalate") {
        reasons.push(judged.reason || "the judge asks for approval");
        return [tighten(effect, "require_approval"), undefined];
      }
    } catch (error) {
      // A failing judge can't let a call through, nor stop it alone.
      reasons.push(`the judge failed (${error instanceof Error ? error.name : typeof error})`);
      return [tighten(effect, "require_approval"), undefined];
    }
    return [effect, undefined];
  }

  private approval(effect: PolicyEffect, role: string | null, reasons: string[], approval: ApprovalDecision | null): ToolVerdict {
    if (effect !== "require_approval") return { decision: "allow", step: 7, code: null, reason: "allowed", approver_role: null };
    if (approval && approval.decision !== "reject") {
      return { decision: "allow", step: 7, code: "approved", reason: `approved by ${approval.approver.id}`, approver_role: null };
    }
    return { decision: "require_approval", step: 7, code: "approval_required", reason: reasons.join("; "), approver_role: role };
  }

  /** Step 9: sanitizers, truncation and the untrusted label, traced when they change it. */
  async sanitize(run: GovernedRun, call: ToolCall, tool: ToolDescription, result: ToolResult): Promise<ToolResult> {
    const policy: OutputPolicy = tool.manifest?.spec.output ?? {};
    const limit = policy.max_bytes || this.settings.max_output_bytes || 20_000;
    const [cleaned, done] = await sanitize(result, policy, limit);
    if (done.length) {
      run.trace.note(SOURCE, `tool ${call.name} output: ${done.join(", ")}`, {
        hook: "tool.after",
        code: "output_sanitized",
        details: { tool: call.name, step: 9 },
      });
    }
    return cleaned;
  }
}
