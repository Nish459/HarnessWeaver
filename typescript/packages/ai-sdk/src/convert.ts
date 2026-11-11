/**
 * AI SDK model calls as HarnessWeaver's neutral contracts, and back (R7).
 *
 * Hook payloads only ever hold neutral `ModelRequest` and `ModelResponse` values. A
 * request keeps, for each neutral message, where it came from in the AI SDK prompt, so
 * text that `model.before` middleware changed (a redaction) can be written back into the
 * call the model receives. The same approach as Python's `harnessweaver_pydantic_ai.convert`.
 */

import type {
  LanguageModelV4,
  LanguageModelV4CallOptions,
  LanguageModelV4Content,
  LanguageModelV4GenerateResult,
  LanguageModelV4Message,
  LanguageModelV4ToolResultOutput,
  LanguageModelV4Usage,
} from "@ai-sdk/provider";
import { ModelRefusal, type JsonObject, type JsonValue, type Message, type ModelRequest, type ModelResponse, type ToolCall, type ToolSpec, type Usage } from "@harnessweaver/core";

/**
 * Where a neutral message came from: `[message, part]` in the prompt (`part` is -1 for a
 * system message), or null for the model's own earlier answers, which are never rewritten.
 */
export type Where = readonly [message: number, part: number] | null;

/** A JSON object from a tool call's input: parsed when it's JSON text, wrapped otherwise. */
function argumentsOf(input: unknown): JsonObject {
  let value = input;
  if (typeof input === "string") {
    try {
      value = JSON.parse(input);
    } catch {
      return { input };
    }
  }
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as JsonObject) : { input: (value ?? null) as JsonValue };
}

/** The text a tool result shows the model, or undefined when it holds none. */
function resultText(output: LanguageModelV4ToolResultOutput): string | undefined {
  if (output.type === "text" || output.type === "error-text") return output.value;
  if (output.type === "json" || output.type === "error-json") return JSON.stringify(output.value);
  return undefined; // Denials and multi-part content aren't checked; add when a guard needs them
}

/** The neutral messages for one AI SDK prompt message, with where each came from. */
function messagesOf(message: LanguageModelV4Message, i: number): [Message, Where][] {
  if (message.role === "system") return [[{ role: "system", content: message.content }, [i, -1]]];
  const found: [Message, Where][] = [];
  message.content.forEach((part, j) => {
    if (part.type === "text") {
      found.push([{ role: message.role === "assistant" ? "assistant" : "user", content: part.text }, message.role === "assistant" ? null : [i, j]]);
    } else if (part.type === "tool-call") {
      found.push([{ role: "assistant", tool_calls: [{ id: part.toolCallId, name: part.toolName, arguments: argumentsOf(part.input) }] }, null]);
    } else if (part.type === "tool-result") {
      const text = resultText(part.output);
      if (text !== undefined) found.push([{ role: "tool", content: text, tool_call_id: part.toolCallId, name: part.toolName }, [i, j]]);
    }
  });
  return found;
}

/**
 * The neutral request for an AI SDK call, and where each of its messages came from.
 *
 * @param alias The spec's name for the model (`models.allowed_aliases`), when the app gave one.
 */
export function toRequest(params: LanguageModelV4CallOptions, model: LanguageModelV4, alias: string | null, stream: boolean): [ModelRequest, Where[]] {
  const pairs = params.prompt.flatMap(messagesOf);
  const tools: ToolSpec[] = (params.tools ?? []).flatMap((tool) =>
    tool.type === "function" ? [{ name: tool.name, description: tool.description ?? "", input_schema: tool.inputSchema as JsonObject }] : [],
  );
  const format = params.responseFormat;
  const request: ModelRequest = {
    alias,
    model: model.modelId,
    messages: pairs.map(([message]) => message),
    tools,
    output_schema: format?.type === "json" ? ((format.schema ?? {}) as JsonObject) : null,
    temperature: params.temperature ?? null,
    max_tokens: params.maxOutputTokens ?? null,
    stream,
  };
  return [request, pairs.map(([, where]) => where)];
}

/**
 * The call with the text `model.before` middleware changed written back, for this call only.
 * New message and part objects are made, so the app's own prompt keeps what it had.
 * Messages a middleware added or removed are ignored, as in Python.
 */
export function applyRequest(params: LanguageModelV4CallOptions, where: readonly Where[], before: ModelRequest, after: ModelRequest): LanguageModelV4CallOptions {
  const prompt = [...params.prompt];
  where.forEach((found, k) => {
    const text = after.messages[k]?.content ?? "";
    if (found === null || after.messages[k] === undefined || before.messages[k]?.content === text) return;
    const [i, j] = found;
    const message = prompt[i]!;
    if (message.role === "system") {
      prompt[i] = { ...message, content: text };
      return;
    }
    const parts: unknown[] = [...message.content];
    const part = parts[j] as { type: string; output?: LanguageModelV4ToolResultOutput };
    if (part.type === "text") parts[j] = { ...part, text };
    else parts[j] = { ...part, output: { type: part.output?.type === "error-text" || part.output?.type === "error-json" ? "error-text" : "text", value: text } };
    prompt[i] = { ...message, content: parts } as LanguageModelV4Message;
  });
  return { ...params, prompt };
}

/** The neutral usage for AI SDK usage. */
export function usageOf(usage: LanguageModelV4Usage): Usage {
  return { input_tokens: usage.inputTokens.total ?? 0, output_tokens: usage.outputTokens.total ?? 0 };
}

/** An AI SDK model's answer as the neutral response hooks see. */
export function toResponse(result: LanguageModelV4GenerateResult, model: LanguageModelV4): ModelResponse {
  const toolCalls: ToolCall[] = result.content.flatMap((part) => (part.type === "tool-call" ? [{ id: part.toolCallId, name: part.toolName, arguments: argumentsOf(part.input) }] : []));
  return {
    model: result.response?.modelId ?? model.modelId,
    text: result.content.map((part) => (part.type === "text" ? part.text : "")).join(""),
    tool_calls: toolCalls,
    usage: usageOf(result.usage),
    finish_reason: result.finishReason.unified,
  };
}

/**
 * The error for an answer the model declined, keeping what it used but none of its text
 * (R9). AI SDK providers report that as `content-filter`, also what a content filter sets
 * when it cuts an answer short; either way the answer can't be used.
 *
 * @param blockEmpty Also treat an answer with no text and no tool calls as declined.
 */
export function refusalOf(response: ModelResponse, blockEmpty = false): ModelRefusal | undefined {
  const empty = blockEmpty && !response.text && !response.tool_calls?.length;
  if (response.finish_reason !== "content-filter" && !empty) return undefined;
  return new ModelRefusal(undefined, { ...response, text: "", tool_calls: [] });
}

/** The model's answer with its text replaced, when `model.after` middleware changed it. */
export function patchText(result: LanguageModelV4GenerateResult, text: string): LanguageModelV4GenerateResult {
  if (result.content.map((part) => (part.type === "text" ? part.text : "")).join("") === text) return result;
  // The whole new text goes where the first text part was; the other text parts go.
  const content: LanguageModelV4Content[] = [];
  let placed = false;
  for (const part of result.content) {
    if (part.type !== "text") content.push(part);
    else if (!placed) {
      content.push({ ...part, text });
      placed = true;
    }
  }
  if (!placed) content.unshift({ type: "text", text });
  return { ...result, content };
}
