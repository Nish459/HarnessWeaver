/** What the built-in guards share: pattern hits, redaction and verdicts. */

import type { Envelope } from "../envelope.js";
import type { Finding, GuardAction, GuardResult } from "../contracts.js";

/** The port every guardrail implements: check one piece of content (DESIGNS No. 20). */
export interface Guardrail {
  check(content: string, env: Envelope): Promise<GuardResult> | GuardResult;
}

export const ALLOW: GuardResult = { action: "allow", content: null, reason: null, findings: [], score: null };

export interface Hit {
  start: number;
  end: number;
  type: string;
  replacement: string;
  order: number;
}

/** A pattern as the guards' contract writes them: global, maybe case-insensitive. */
export function compilePattern(pattern: string, ignoreCase = false): RegExp {
  return new RegExp(pattern, ignoreCase ? "gi" : "g");
}

/** A string's characters (code points), so positions and lengths agree with Python. */
export function codePoints(text: string): string[] {
  return [...text];
}

/** Every match of `pattern` in `text`, with code-point offsets. */
export function matchesOf(pattern: RegExp, text: string): { start: number; end: number; text: string }[] {
  const found: { start: number; end: number; text: string }[] = [];
  for (const match of text.matchAll(pattern)) {
    const start = codePoints(text.slice(0, match.index)).length;
    found.push({ start, end: start + codePoints(match[0]).length, text: match[0] });
  }
  return found;
}

/**
 * Replace non-overlapping hits: the earliest start wins, then the longest, then list
 * order. `private` marks the findings as private data (S3).
 */
export function applyHits(content: string, hits: Hit[], isPrivate = false): [string, Finding[]] {
  const chosen: Hit[] = [];
  const sorted = [...hits].sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start) || a.order - b.order);
  for (const hit of sorted) {
    const last = chosen.at(-1);
    if (last !== undefined && hit.start < last.end) continue;
    chosen.push(hit);
  }
  let chars = codePoints(content);
  for (const hit of [...chosen].reverse()) chars = [...chars.slice(0, hit.start), hit.replacement, ...chars.slice(hit.end)];
  const findings: Finding[] = chosen.map((h) => ({ type: h.type, start: h.start, end: h.end, score: null, private: isPrivate }));
  return [chars.join(""), findings];
}

export function verdictOf(action: GuardAction, content: string, findings: Finding[], reason: string): GuardResult {
  if (findings.length === 0) return ALLOW;
  return { action, content, findings, reason, score: null };
}

export function findingTypes(findings: readonly Finding[]): string {
  return [...new Set(findings.map((f) => f.type))].sort().join(", ");
}

/** `re.escape`, for keywords in a pattern. */
export function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\\-/]/g, "\\$&");
}
