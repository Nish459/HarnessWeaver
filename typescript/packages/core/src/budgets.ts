/**
 * Budget accounting and cost resolution (DESIGNS No. 10, ADR-0012, fixtures suite
 * `budgets`).
 *
 * A meter counts what one run has used and says which limit a step would breach:
 * at `model.before` the calls, tokens and cost so far (and whether the next request's
 * estimated input fits), at `model.after` the actual usage and cost, at `tool.before`
 * the tool calls. Cost comes from the provider, then `models.prices`, else it is
 * unknown: flagged, never guessed.
 */

import type { Budget, ModelRequest, ModelResponse, Usage } from "./contracts.js";
import type { Block } from "./outcomes.js";

export const BUDGET_CODE = "budget_exceeded";

export type Limit = "max_usd" | "max_tokens" | "max_model_calls" | "max_tool_calls";
export type CostSource = "provider" | "prices" | "unknown";

/** `model -> [USD per million input tokens, USD per million output tokens]`. */
export type PriceLookup = (model: string) => readonly [number, number] | undefined;

/** One token per four characters, counting code points so every language agrees. */
export function estimateTokens(request: ModelRequest): number {
  const chars = request.messages.reduce((sum, message) => sum + [...(message.content ?? "")].length, 0);
  return Math.ceil(chars / 4);
}

/** The USD cost of one call and where it came from; prices by response model, request model, then alias. */
export function resolveCost(response: ModelResponse, request: ModelRequest, prices?: PriceLookup): [number | null, CostSource] {
  if (response.cost_usd !== null && response.cost_usd !== undefined) return [response.cost_usd, "provider"];
  if (prices !== undefined) {
    for (const model of [response.model, request.model, request.alias]) {
      const price = model ? prices(model) : undefined;
      if (price !== undefined) {
        const usage = response.usage ?? {};
        return [((usage.input_tokens ?? 0) * price[0] + (usage.output_tokens ?? 0) * price[1]) / 1_000_000, "prices"];
      }
    }
  }
  return [null, "unknown"];
}

/** The Block a breached limit turns into. */
export function breachBlock(limit: Limit, limits: Budget): Block {
  return { kind: "block", reason: `budget ${limit} (${limits[limit]}) reached`, code: BUDGET_CODE };
}

/** The tighter of two budgets, field by field. */
export function intersectBudgets(a: Budget, b: Budget): Budget {
  const tighter = (x: number | null | undefined, y: number | null | undefined): number | null =>
    x === null || x === undefined ? (y ?? null) : y === null || y === undefined ? x : Math.min(x, y);
  return {
    max_usd: tighter(a.max_usd, b.max_usd),
    max_tokens: tighter(a.max_tokens, b.max_tokens),
    max_model_calls: tighter(a.max_model_calls, b.max_model_calls),
    max_tool_calls: tighter(a.max_tool_calls, b.max_tool_calls),
    deadline: tighter(a.deadline, b.deadline),
  };
}

function totalTokens(usage: Usage): number {
  return (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0);
}

/** What one run has used against its limits. */
export class BudgetMeter {
  usd = 0;
  costKnown = true;
  usage: Required<Usage> = { input_tokens: 0, output_tokens: 0 };
  modelCalls = 0;
  toolCalls = 0;

  constructor(readonly limits: Budget) {}

  /** The limit the next model call would breach, or undefined if it may go ahead. */
  checkModelCall(request: ModelRequest): Limit | undefined {
    const { max_model_calls, max_tokens, max_usd } = this.limits;
    if (max_model_calls != null && this.modelCalls >= max_model_calls) return "max_model_calls";
    if (max_tokens != null) {
      const used = totalTokens(this.usage);
      if (used >= max_tokens || used + estimateTokens(request) > max_tokens) return "max_tokens";
    }
    if (max_usd != null && this.usd >= max_usd) return "max_usd";
    return undefined;
  }

  startModelCall(): void {
    this.modelCalls += 1;
  }

  /** Add a call's usage and cost; return the limit it went over, if any. */
  recordModelCall(usage: Usage, cost: number | null): Limit | undefined {
    this.usage = {
      input_tokens: this.usage.input_tokens + (usage.input_tokens ?? 0),
      output_tokens: this.usage.output_tokens + (usage.output_tokens ?? 0),
    };
    if (cost === null) this.costKnown = false;
    else this.usd += cost;
    const { max_tokens, max_usd } = this.limits;
    if (max_tokens != null && totalTokens(this.usage) > max_tokens) return "max_tokens";
    if (max_usd != null && this.usd > max_usd) return "max_usd";
    return undefined;
  }

  /** The limit the next tool call would breach, or undefined. */
  checkToolCall(): Limit | undefined {
    const limit = this.limits.max_tool_calls;
    return limit != null && this.toolCalls >= limit ? "max_tool_calls" : undefined;
  }

  startToolCall(): void {
    this.toolCalls += 1;
  }

  /** What is left of each limit, never negative. */
  remaining(timeLeft?: number | null): Budget {
    const left = (limit: number | null | undefined, used: number): number | null => (limit == null ? null : Math.max(limit - used, 0));
    return {
      max_usd: left(this.limits.max_usd, this.usd),
      max_tokens: left(this.limits.max_tokens, totalTokens(this.usage)),
      max_model_calls: left(this.limits.max_model_calls, this.modelCalls),
      max_tool_calls: left(this.limits.max_tool_calls, this.toolCalls),
      deadline: timeLeft ?? this.limits.deadline ?? null,
    };
  }
}
