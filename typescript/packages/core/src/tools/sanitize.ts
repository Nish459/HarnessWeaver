/**
 * Governor step 9: what a tool's result goes through before anything else sees it. In
 * order: the manifest's sanitizers (`pii_redact`, then `strip_instructions`),
 * truncation to `max_bytes` of UTF-8, and the `untrusted` label (S3). Truncated output
 * becomes a string: a JSON result is cut as its compact JSON text.
 */

import type { ToolResult } from "../contracts.js";
import { INJECTION_PATTERNS, PiiRegex } from "../guards/providers.js";
import type { JsonValue } from "../json.js";
import type { OutputPolicy } from "./manifests.js";

/** What `strip_instructions` puts in place of an instruction-like phrase. */
export const REMOVED = "[removed]";

const INSTRUCTIONS = INJECTION_PATTERNS.map(([, pattern]) => new RegExp(pattern, "gi"));
const PII = new PiiRegex();
const ENCODER = new TextEncoder();
const DECODER = new TextDecoder("utf-8", { fatal: false });

async function strings(value: JsonValue | undefined, change: (text: string) => Promise<string> | string): Promise<JsonValue | undefined> {
  if (typeof value === "string") return change(value);
  if (Array.isArray(value)) return Promise.all(value.map(async (item) => (await strings(item, change)) as JsonValue));
  if (value !== null && typeof value === "object") {
    const entries = await Promise.all(Object.entries(value).map(async ([k, item]) => [k, await strings(item, change)] as const));
    return Object.fromEntries(entries) as JsonValue;
  }
  return value;
}

/** Cut text to `maxBytes` of UTF-8, dropping a character the cut would split. */
function cut(text: string, maxBytes: number): string {
  const bytes = ENCODER.encode(text);
  let end = Math.min(maxBytes, bytes.length);
  // A continuation byte (10xxxxxx) just past the cut means a character is split:
  // back up to that character's first byte.
  while (end > 0 && end < bytes.length && ((bytes[end] ?? 0) & 0xc0) === 0x80) end -= 1;
  return DECODER.decode(bytes.slice(0, end));
}

/** Apply `policy` to `result`; returns the new result and what was done, for the trace. */
export async function sanitize(result: ToolResult, policy: OutputPolicy, maxBytes: number): Promise<[ToolResult, string[]]> {
  let output = result.output;
  const done: string[] = [];
  const steps: [string, (text: string) => string][] = [
    ["pii_redact", (text) => PII.check(text).content ?? text],
    ["strip_instructions", (text) => INSTRUCTIONS.reduce((t, pattern) => t.replace(pattern, REMOVED), text)],
  ];
  for (const [name, change] of steps) {
    if ((policy.sanitize ?? []).includes(name as "pii_redact")) {
      const changed = await strings(output, change);
      if (JSON.stringify(changed) !== JSON.stringify(output)) done.push(name);
      output = changed;
    }
  }
  let truncated = result.truncated ?? false;
  const text = typeof output === "string" ? output : JSON.stringify(output ?? null);
  if (ENCODER.encode(text).length > maxBytes) {
    output = cut(text, maxBytes);
    truncated = true;
    done.push(`truncated to ${maxBytes} bytes`);
  }
  const untrusted = (policy.label ?? "untrusted") === "untrusted";
  return [{ ...result, output: output ?? null, truncated, untrusted }, done];
}
