/** Runner for the `routing` suite: tokens, similarity, embeddings, stages, the cascade. */

import { describe, expect, it } from "vitest";
import type { Decision } from "../src/contracts.js";
import { decideInCascade, LexicalDecider, RulesDecider, type Stage } from "../src/routing.js";
import { cosine, hashingEmbedding, lexicalSimilarity, tokens } from "../src/text.js";
import { casesOf } from "./fixtures.js";

const round = (value: number): number => Math.round(value * 1e6) / 1e6;

function shape(decision: Decision) {
  return { kind: decision.kind, choice: decision.choice ?? null, confidence: decision.confidence == null ? null : round(decision.confidence) };
}

describe("routing", () => {
  it.each(casesOf("routing"))("%s", async (_, c) => {
    const want = c.expect;
    if ("tokens" in c) {
      expect(tokens(c.tokens)).toEqual(want.tokens);
    } else if ("embed" in c) {
      expect(hashingEmbedding(c.embed, c.dims).map(round)).toEqual(want.vector);
    } else if ("cosine" in want) {
      expect(round(cosine(hashingEmbedding(c.a, c.dims), hashingEmbedding(c.b, c.dims)))).toBe(want.cosine);
    } else if ("similarity" in want) {
      expect(round(lexicalSimilarity(c.a, c.b))).toBe(want.similarity);
    } else if ("stage" in c) {
      const decider = c.stage === "rules" ? new RulesDecider(c.config.rules ?? []) : new LexicalDecider(c.config.utterances ?? {});
      expect(shape(await decider.decide(c.request))).toEqual(want);
    } else {
      const stages: Stage[] = c.stages.map((spec: Record<string, any>, i: number) => ({
        label: `s${i + 1}`,
        threshold: spec.threshold ?? null,
        decider: () => {
          if (spec.error) throw new Error("stage down");
          return { choice: null, confidence: null, reason: null, stage: null, ...spec.answer };
        },
      }));
      const won: boolean[] = [];
      const decision = await decideInCascade("r", stages, c.options, c.default, (d) => d({ router: "r", options: c.options }), (_r, _s, _d, w) => won.push(w));
      expect(decision === undefined ? null : { kind: decision.kind, choice: decision.choice ?? null, stage: decision.stage ?? null }).toEqual(want.decision);
      expect(won).toEqual(want.won);
    }
  });
});
