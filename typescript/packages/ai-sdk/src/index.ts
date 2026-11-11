/**
 * `@harnessweaver/ai-sdk`: Vercel AI SDK models governed by a HarnessWeaver session.
 *
 *     import { generateText } from "ai";
 *     import { wrapModel } from "@harnessweaver/ai-sdk";
 *
 *     await harness.session({ principal: user.id }, async (s) => {
 *       const { text } = await generateText({ model: wrapModel(s, openai("gpt-5")), prompt });
 *       return s.validate("output", text);
 *     });
 *
 * Every call through the wrapped model checks `models.allowed_aliases` and the run's
 * budget, fires `model.before` (whose redactions reach the model) and `model.after`
 * (whose redactions reach the app), and meters usage and cost. A streamed call also
 * fires `stream.chunk` for each text delta, so stream guards can redact or cut it.
 * A halting outcome throws a `RunInterrupted` error, from the call or the stream. So does
 * an answer the model declined: a `ModelRefusal`, whose usage and cost still count.
 */

import type { LanguageModelV4, LanguageModelV4Middleware, LanguageModelV4StreamPart } from "@ai-sdk/provider";
import type { Session } from "@harnessweaver/core";
import { wrapLanguageModel } from "ai";
import { applyRequest, patchText, refusalOf, toRequest, toResponse, usageOf } from "./convert.js";

export { applyRequest, patchText, refusalOf, toRequest, toResponse, type Where } from "./convert.js";

export interface WrapOptions {
  /** The spec's name for this model, checked against `models.allowed_aliases`. */
  alias?: string;
  /**
   * Deliver a streamed answer's parts only once it has finished, so nothing from a declined
   * answer reaches the app. Output is no longer live.
   */
  holdStream?: boolean;
  /**
   * Treat an answer with no text and no tool calls as declined. Some providers drop a
   * model's refusal, leaving only that; but a model may also just have nothing to add.
   */
  blockEmptyAnswers?: boolean;
}

/**
 * The AI SDK middleware that governs calls with `session`'s run. `wrapModel` is the
 * usual way in; use this to compose with other AI SDK middleware.
 */
export function harnessMiddleware(session: Session, options: WrapOptions = {}): LanguageModelV4Middleware {
  const run = session.run;
  const alias = options.alias ?? null;
  return {
    specificationVersion: "v4",

    async wrapGenerate({ params, model }) {
      const [request, where] = toRequest(params, model, alias, false);
      let answer: Awaited<ReturnType<LanguageModelV4["doGenerate"]>> | undefined;
      // The model's own errors pass through unchanged, so the AI SDK's retries
      // (which look for its own error types) keep working; run.end records the failure.
      const response = await session.generate(request, async (sent) => {
        answer = await model.doGenerate(applyRequest(params, where, request, sent));
        const neutral = toResponse(answer, model);
        const refusal = refusalOf(neutral, options.blockEmptyAnswers);
        if (refusal !== undefined) throw refusal;
        return neutral;
      });
      return patchText(answer!, response.text ?? "");
    },

    async wrapStream({ params, model }) {
      const [request, where] = toRequest(params, model, alias, true);
      const sent = await run.startModelCall(request);
      const { stream, ...rest } = await model.doStream(applyRequest(params, where, request, sent));
      // Each text delta goes through stream.chunk before the app sees it; the finish part
      // closes the call (usage, cost, model.after). A halting outcome errors the stream.
      // A Retry at model.after can't re-ask a model whose words were already sent, so it blocks.
      // The refusal signal only comes with the finish part, so holdStream keeps every part until then.
      let text = "";
      let index = 0;
      let called = false;
      const held: LanguageModelV4StreamPart[] = [];
      const governed = new TransformStream<LanguageModelV4StreamPart, LanguageModelV4StreamPart>({
        async transform(part, controller) {
          const send = (out: LanguageModelV4StreamPart): void => {
            if (options.holdStream) held.push(out);
            else controller.enqueue(out);
          };
          if (part.type === "text-delta") {
            const chunk = await run.streamChunk(sent, { index: index++, delta: part.delta }, text);
            text += chunk.delta ?? "";
            send({ ...part, delta: chunk.delta ?? "" });
            return;
          }
          called ||= part.type === "tool-call";
          if (part.type !== "finish") {
            send(part);
            return;
          }
          const neutral = { model: model.modelId, text, usage: usageOf(part.usage), finish_reason: part.finishReason.unified };
          const refusal = refusalOf(neutral, options.blockEmptyAnswers && !called);
          if (refusal !== undefined) throw run.refuseModelCall(sent, refusal);
          const [, retry] = await run.finishModelCall(sent, neutral);
          if (retry !== undefined) throw run.interrupt("model.after", retry);
          held.splice(0).forEach((out) => controller.enqueue(out));
          controller.enqueue(part);
        },
        flush(controller) {
          // A stream that ended with no finish part carries no signal, so what it sent goes out.
          held.splice(0).forEach((out) => controller.enqueue(out));
        },
      });
      return { ...rest, stream: stream.pipeThrough(governed) };
    },
  };
}

/** `model`, with every call governed by `session`'s run (see the module docs). */
export function wrapModel(session: Session, model: LanguageModelV4, options: WrapOptions = {}): LanguageModelV4 {
  return wrapLanguageModel({ model, middleware: harnessMiddleware(session, options) });
}
