/**
 * The offline model: an AI SDK model that answers from the spec's `models.rules` and
 * `models.replies`, as Python's `scripted` provider does. So `HARNESSWEAVER_ENV=offline`
 * gives the TypeScript app the same answers as Example 02's Python one, with no network
 * and no model spend (R14).
 */

import type { LanguageModelV4, LanguageModelV4Prompt } from "@ai-sdk/provider";
import { estimateTokens, ProviderError, SpecError, type JsonObject } from "@harnessweaver/core";

interface Reply {
  text: string;
}

interface Rule {
  contains: string;
  reply: Reply;
}

/** The parts of a `models` section the offline model reads. */
export interface Script {
  rules?: Rule[];
  replies?: Reply[];
}

/** Refuse a key this port doesn't read, so it never answers differently from Python. */
function onlyKeys(value: unknown, keys: readonly string[], where: string): void {
  const extra = Object.keys(value as JsonObject).filter((key) => !keys.includes(key));
  if (extra.length) throw new SpecError(`${where}: the TypeScript offline model doesn't read ${extra.join(", ")}`);
}

/** The text of the last message, which rules match, as in Python. */
function lastText(prompt: LanguageModelV4Prompt): string {
  const last = prompt.at(-1);
  if (last === undefined) return "";
  if (last.role === "system") return last.content;
  return last.content.map((part) => (part.type === "text" ? part.text : "")).join("");
}

/**
 * A model that answers by the script: the first rule whose `contains` is in the last
 * message (ignoring case), else the next reply, the last one repeating.
 *
 * @throws SpecError for a script that uses fields this port doesn't read.
 */
// Only what Example 02's overlay uses (contains, text); port the rest of
// Python's ScriptedModel into @harnessweaver/ai-sdk when a second app needs it.
export function scriptedModel(script: Script): LanguageModelV4 {
  const rules = script.rules ?? [];
  const replies = script.replies ?? [];
  rules.forEach((rule, i) => {
    onlyKeys(rule, ["contains", "reply"], `models.rules[${i}]`);
    onlyKeys(rule.reply, ["text"], `models.rules[${i}].reply`);
  });
  replies.forEach((reply, i) => onlyKeys(reply, ["text"], `models.replies[${i}]`));
  let next = 0;
  return {
    specificationVersion: "v4",
    provider: "scripted",
    modelId: "scripted",
    supportedUrls: {},
    async doGenerate({ prompt }) {
      const said = lastText(prompt).toLowerCase();
      const reply = rules.find((rule) => said.includes(rule.contains.toLowerCase()))?.reply ?? replies[Math.min(next++, replies.length - 1)];
      if (reply === undefined) throw new ProviderError("the script has no reply for this request");
      // Usage is estimated as Python's scripted provider does: about four characters a token.
      const asked = estimateTokens({ messages: [{ role: "user", content: prompt.map((message) => JSON.stringify(message.content)).join("") }] });
      const told = estimateTokens({ messages: [{ role: "assistant", content: reply.text }] });
      return {
        content: [{ type: "text", text: reply.text }],
        finishReason: { unified: "stop", raw: undefined },
        usage: { inputTokens: { total: asked, noCache: asked, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: told, text: told, reasoning: 0 } },
        warnings: [],
      };
    },
    async doStream() {
      throw new ProviderError("the offline model doesn't stream");
    },
  };
}
