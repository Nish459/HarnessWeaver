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
 * A halting outcome throws a `RunInterrupted` error, from the call or the stream.
 */

import type { LanguageModelV4, LanguageModelV4Middleware, LanguageModelV4StreamPart } from "@ai-sdk/provider";
import type { Session } from "@harnessweaver/core";
import { wrapLanguageModel } from "ai";
import { applyRequest, patchText, toRequest, toResponse, usageOf } from "./convert.js";

export { applyRequest, patchText, toRequest, toResponse, type Where } from "./convert.js";

export interface WrapOptions {
  /** The spec's name for this model, checked against `models.allowed_aliases`. */
  alias?: string;
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
      // ponytail: the model's own errors pass through unchanged, so the AI SDK's retries
      // (which look for its own error types) keep working; run.end records the failure.
      const response = await session.generate(request, async (sent) => {
        answer = await model.doGenerate(applyRequest(params, where, request, sent));
        return toResponse(answer, model);
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
      let text = "";
      let index = 0;
      const governed = new TransformStream<LanguageModelV4StreamPart, LanguageModelV4StreamPart>({
        async transform(part, controller) {
          if (part.type === "text-delta") {
            const chunk = await run.streamChunk(sent, { index: index++, delta: part.delta }, text);
            text += chunk.delta ?? "";
            controller.enqueue({ ...part, delta: chunk.delta ?? "" });
            return;
          }
          if (part.type === "finish") {
            const [, retry] = await run.finishModelCall(sent, { model: model.modelId, text, usage: usageOf(part.usage), finish_reason: part.finishReason.unified });
            if (retry !== undefined) throw run.interrupt("model.after", retry);
          }
          controller.enqueue(part);
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
