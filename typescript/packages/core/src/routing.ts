/**
 * Routing (DESIGNS No. 19, ADR-0029, fixtures suite `routing`): the `rules` and
 * `lexical` stages and the cascade that runs them, one `route.decide` middleware per
 * router. Stages run in order and the first confident answer wins: an exact answer is
 * confident; a probabilistic one when it reaches the stage's threshold (any, without
 * one); an answer outside the options, or a stage that fails, abstains. With no
 * confident stage the router's `default` answers. Every stage's answer is traced (R13).
 * Stage reasons name rules, options and scores, never the text (R9).
 */

import { readFileSync } from "node:fs";
import { parse as parseYaml } from "yaml";
import type { Decision, DecisionRequest } from "./contracts.js";
import { currentRun } from "./current.js";
import { ExpressionError, ExpressionSyntaxError, SpecError } from "./errors.js";
import { compileExpression, type Expression } from "./expr/index.js";
import type { RouteEvent } from "./hooks.js";
import type { JsonObject } from "./json.js";
import type { Handler } from "./middleware.js";
import { defineProvider } from "./plugins/provider.js";
import { lexicalSimilarity } from "./text.js";

/** One routing stage: answers a request with a decision (port `Decider`). */
export type Decider = (request: DecisionRequest) => Promise<Decision> | Decision;

/** Names a routing rule's `when` may use. */
export const RULE_VARIABLES = ["text", "state", "options", "router"];

const exact = (choice: string, reason: string): Decision => ({ kind: "exact", choice, confidence: 1, reason, stage: null });
const abstain = (reason: string): Decision => ({ kind: "abstain", choice: null, confidence: null, reason, stage: null });

function fromFile(path: unknown, key: string): unknown {
  if (typeof path !== "string") return undefined;
  const document = parseYaml(readFileSync(path, "utf8"), { version: "1.2", uniqueKeys: true });
  if (document === null || typeof document !== "object" || !(key in document)) throw new SpecError(`${path} must be a map with '${key}'`);
  return (document as JsonObject)[key];
}

interface RouteRule {
  id?: string | null;
  when: string;
  choice: string;
  reason?: string | null;
}

/** The first rule whose `when` is true decides, exactly; otherwise it abstains. */
export class RulesDecider {
  private readonly rules: [RouteRule, Expression][];

  /** @throws SpecError for a rule that doesn't compile. */
  constructor(rules: readonly RouteRule[] = [], file?: string) {
    const listed = [...rules, ...((fromFile(file, "rules") as RouteRule[] | undefined) ?? [])];
    this.rules = listed.map((rule, index) => {
      try {
        return [rule, compileExpression(rule.when, RULE_VARIABLES)];
      } catch (error) {
        if (error instanceof ExpressionSyntaxError) throw new SpecError(`routing rule ${rule.id ?? index}: ${error.message}`);
        throw error;
      }
    });
  }

  get choices(): Set<string> {
    return new Set(this.rules.map(([rule]) => rule.choice));
  }

  decide = (request: DecisionRequest): Decision => {
    const variables = { text: request.text ?? "", state: request.state ?? {}, options: request.options ?? [], router: request.router };
    let unchecked = 0;
    for (const [index, [rule, expression]] of this.rules.entries()) {
      let matched: boolean;
      try {
        matched = expression.evaluateBool(variables);
      } catch (error) {
        if (!(error instanceof ExpressionError)) throw error;
        unchecked += 1;
        continue;
      }
      if (matched) return exact(rule.choice, rule.reason || `rule ${rule.id || index + 1}`);
    }
    return abstain(`no rule matched${unchecked ? ` (${unchecked} couldn't be checked)` : ""}`);
  };
}

/**
 * Scores each option by its closest utterance (token cosine); the best wins, with its
 * score as the confidence. No shared words: it abstains.
 */
export class LexicalDecider {
  readonly utterances: Map<string, string[]>;

  constructor(utterances: Record<string, readonly string[]> = {}, file?: string) {
    this.utterances = new Map(Object.entries(utterances).map(([option, texts]) => [option, [...texts]]));
    const loaded = fromFile(file, "utterances");
    if (loaded !== undefined) {
      if (loaded === null || typeof loaded !== "object" || Array.isArray(loaded)) throw new SpecError(`${file}: utterances must map options to lists of texts`);
      for (const [option, texts] of Object.entries(loaded)) {
        this.utterances.set(option, [...(this.utterances.get(option) ?? []), ...(texts as unknown[]).map(String)]);
      }
    }
    if (this.utterances.size === 0) throw new SpecError("a lexical or semantic stage needs utterances");
  }

  get choices(): Set<string> {
    return new Set(this.utterances.keys());
  }

  decide = (request: DecisionRequest): Decision => {
    const text = request.text ?? "";
    const scores = new Map<string, number>();
    for (const [option, texts] of this.utterances) {
      if (texts.length) scores.set(option, Math.max(...texts.map((u) => lexicalSimilarity(text, u))));
    }
    // The best-scoring option; ties go to the option listed first.
    const options = request.options ?? [];
    let best: [string | null, number] = [null, 0];
    for (const option of [...options, ...[...scores.keys()].filter((o) => !options.includes(o))]) {
      const score = scores.get(option) ?? 0;
      if (score > best[1]) best = [option, score];
    }
    const [choice, score] = best;
    if (choice === null) return abstain("no utterance shares a word with the text");
    return { kind: "probabilistic", choice, confidence: Math.round(score * 1e6) / 1e6, reason: `closest to ${choice}`, stage: null };
  };
}

const TEXTS = { type: "array", items: { type: "string" } };
const NULLABLE_STRING = { anyOf: [{ type: "string" }, { type: "null" }], default: null };

export const rulesStage = defineProvider({
  port: "Decider",
  name: "rules",
  deterministic: true,
  settings: {
    properties: {
      rules: {
        type: "array",
        default: [],
        items: {
          type: "object",
          additionalProperties: false,
          required: ["when", "choice"],
          properties: { id: { anyOf: [{ type: "string" }, { type: "null" }] }, when: { type: "string" }, choice: { type: "string" }, reason: { anyOf: [{ type: "string" }, { type: "null" }] } },
        },
      },
      file: NULLABLE_STRING,
    },
  },
  create: (s) => new RulesDecider(s.rules as RouteRule[], (s.file as string | null) ?? undefined),
});

export const lexicalStage = defineProvider({
  port: "Decider",
  name: "lexical",
  deterministic: true,
  settings: {
    properties: {
      utterances: { type: "object", additionalProperties: TEXTS, default: {} },
      file: NULLABLE_STRING,
    },
  },
  create: (s) => new LexicalDecider(s.utterances as Record<string, string[]>, (s.file as string | null) ?? undefined),
});

/** One cascade stage: its label on the trace, its decider and its threshold. */
export interface Stage {
  label: string;
  decider: Decider;
  threshold?: number | null;
}

function confident(stage: Stage, decision: Decision): boolean {
  if (decision.kind === "abstain") return false;
  if (decision.kind !== "probabilistic" || stage.threshold === null || stage.threshold === undefined) return true;
  return (decision.confidence ?? 0) >= stage.threshold;
}

export type StageNote = (router: string, stage: Stage, decision: Decision, won: boolean) => void;

/**
 * Run `stages` on a request (`ask(decider)` returns the stage's answer). The winning
 * decision with its stage, the default, or undefined when every stage abstained.
 */
export async function decideInCascade(
  router: string,
  stages: readonly Stage[],
  options: readonly string[],
  fallback: string | null | undefined,
  ask: (decider: Decider) => Promise<Decision> | Decision,
  note?: StageNote,
): Promise<Decision | undefined> {
  for (const stage of stages) {
    let decision: Decision;
    try {
      decision = await ask(stage.decider);
    } catch (error) {
      // A broken stage abstains; the cascade goes on.
      decision = abstain(`the stage failed (${error instanceof Error ? error.name : typeof error})`);
    }
    if (decision.choice !== null && decision.choice !== undefined && !options.includes(decision.choice)) {
      decision = abstain("it chose something that isn't an option");
    }
    const won = confident(stage, decision);
    note?.(router, stage, decision, won);
    if (won) return { ...decision, stage: stage.label };
  }
  if (fallback === null || fallback === undefined) return undefined;
  return { kind: "default", choice: fallback, confidence: null, reason: "no stage was confident", stage: null };
}

const traceStage: StageNote = (router, stage, decision, won) => {
  const run = currentRun();
  if (run === undefined) return;
  const details: JsonObject = { router, stage: stage.label, kind: decision.kind, won };
  if (decision.choice != null) details.choice = decision.choice;
  if (decision.confidence != null) details.confidence = decision.confidence;
  if (stage.threshold != null) details.threshold = stage.threshold;
  run.trace.note("harness.routing", decision.reason || decision.kind, { hook: "route.decide", details });
};

/** Middleware that answers `route.decide` for router `name`. */
export function cascadeHandler(name: string, options: readonly string[], fallback: string | null | undefined, stages: readonly Stage[]): Handler {
  return async (event) => {
    const route = event as RouteEvent;
    if (route.request.router !== name || route.decision) return undefined;
    const request = route.request.options?.length ? route.request : { ...route.request, options: [...options] };
    const decision = await decideInCascade(name, stages, request.options ?? [], fallback, (decider) => decider(request), traceStage);
    if (decision === undefined) return undefined;
    return { kind: "continue", modified: { ...route, request, decision } };
  };
}
