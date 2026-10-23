/**
 * Example 02's support flow (`support/flow.py`) in TypeScript: route the question,
 * retrieve articles, answer citing them. The app owns these steps; the session governs
 * each one:
 *
 * 1. `guard("input")` fires `input.before`: the baseline's PII guard redacts, and the rag
 *    profile's injection guard blocks. (In Python the session runner does this step.)
 * 2. `decide` fires `route.decide`: the rules stage, then the lexical stage.
 * 3. `fetch` retrieves articles, re-checks each ACL against the caller's tenant and
 *    principal, labels them untrusted and runs the context guards, which drop an
 *    article carrying an injection. Only what is left reaches the model.
 * 4. The model answers through `wrapModel` (allowed aliases, budgets, `model.before`,
 *    `model.after`), and `validate` runs the output guards: the citation check asks for
 *    a repair, which is tried once, as Python's `Session.generate` does.
 */

import type { LanguageModelV4 } from "@ai-sdk/provider";
import { wrapModel } from "@harnessweaver/ai-sdk";
import { ValidationFailed, type Session } from "@harnessweaver/core";
import { generateText, type ModelMessage } from "ai";

/** An answer to one customer question (Python's `support.models.Reply`). */
export interface Reply {
  /** The kind of question: outage, billing or howto. */
  intent: string;
  answer: string;
  /** Ids of the articles the answer could cite. */
  sources: string[];
}

export const NO_ANSWER = "I don't know; a support agent will follow up.";

/** Repairs before giving up, as `validation.max_repairs` defaults to. */
const MAX_REPAIRS = 1;

/**
 * Answer one customer question from the help center.
 *
 * @throws RunInterrupted when a control halts the run; ValidationFailed when the answer
 *   is still uncited after the repair.
 */
export async function answer(s: Session, question: string, model: LanguageModelV4): Promise<Reply> {
  const asked = String(await s.guard("input", question));
  const route = await s.decide("intent", { text: asked });
  const intent = String(route.choice);
  const articles = await s.context("help").fetch(asked);
  if (articles.length === 0) return { intent, answer: NO_ANSWER, sources: [] }; // nothing this customer may read answers it
  const listing = articles.map((article) => `[${article.id}] ${article.content}`).join("\n");
  const messages: ModelMessage[] = [{ role: "user", content: await s.prompt("answer@1", { question: asked, intent, articles: listing }) }];
  const governed = wrapModel(s, model, { alias: "fast" });
  for (let repairs = 0; ; repairs++) {
    const { text } = await generateText({ model: governed, messages });
    try {
      const checked = await s.validate("output", text);
      return { intent, answer: checked, sources: articles.map((article) => article.id) };
    } catch (error) {
      if (!(error instanceof ValidationFailed) || repairs >= MAX_REPAIRS) throw error;
      // The same repair request Python sends, after the answer that wasn't accepted.
      messages.push(
        { role: "assistant", content: text },
        { role: "user", content: `Your previous answer was not accepted: ${error.message}. Reply again with a corrected answer in the required format.` },
      );
    }
  }
}
