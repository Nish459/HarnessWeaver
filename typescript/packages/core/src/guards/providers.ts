/**
 * The built-in guards (DESIGNS No. 20, fixtures suite `guards`): `regex.deny`,
 * `pii.regex`, `secrets.scan`, `injection.heuristic`, `size.limit`, `topic.deny`,
 * `grounded.citations` and `llm.judge`. Their patterns are part of the contract,
 * written in the regex syntax Python and JavaScript share.
 */

import type { Finding, GuardResult } from "../contracts.js";
import { currentRun } from "../current.js";
import { ProviderError } from "../errors.js";
import { defineProvider, type ProviderDef } from "../plugins/provider.js";
import { tokens } from "../text.js";
import {
  ALLOW,
  applyHits,
  codePoints,
  compilePattern,
  escapeRegExp,
  findingTypes,
  matchesOf,
  verdictOf,
  type Guardrail,
  type Hit,
} from "./common.js";

const ALL_STAGES = ["input", "context", "tool_result", "output", "stream"];

// --- pii.regex --------------------------------------------------------------------------

const OCTET = "(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])";

/** Entity patterns, in the order ties are broken. */
export const PII_PATTERNS: Record<string, string> = {
  EMAIL: "[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,}",
  CREDIT_CARD: "\\b(?:[0-9][ -]?){12,18}[0-9]\\b",
  SSN: "\\b[0-9]{3}-[0-9]{2}-[0-9]{4}\\b",
  PHONE:
    "(?:\\+[0-9]{1,3}[ .-]?)?(?:\\([0-9]{3}\\)[ .-]?|\\b[0-9]{3}[ .-])[0-9]{3}[ .-][0-9]{4}\\b" +
    "|\\+[0-9]{1,3}(?:[ .-][0-9]{1,4}){2,4}\\b",
  IP_ADDRESS: `\\b(?:${OCTET}\\.){3}${OCTET}\\b`,
};

function luhn(digits: string): boolean {
  let total = 0;
  [...digits].reverse().forEach((char, index) => {
    let value = Number(char);
    if (index % 2 === 1) value = value > 4 ? value * 2 - 9 : value * 2;
    total += value;
  });
  return total % 10 === 0;
}

function piiValid(entity: string, text: string): boolean {
  const digits = text.replace(/[^0-9]/g, "");
  if (entity === "CREDIT_CARD") return digits.length >= 13 && digits.length <= 19 && luhn(digits);
  if (entity === "PHONE") return digits.length >= 9 && digits.length <= 15;
  return true;
}

/** Finds emails, phone numbers, Luhn-checked card numbers, US SSNs and IPv4 addresses. */
export class PiiRegex implements Guardrail {
  private readonly patterns: [string, RegExp, number][];

  constructor(
    entities: readonly string[] = Object.keys(PII_PATTERNS),
    private readonly replacement = "[{entity}]",
  ) {
    const order = Object.keys(PII_PATTERNS);
    this.patterns = order.filter((e) => entities.includes(e)).map((e) => [e, compilePattern(PII_PATTERNS[e]!), order.indexOf(e)]);
  }

  check(content: string): GuardResult {
    const hits: Hit[] = [];
    for (const [entity, pattern, rank] of this.patterns) {
      for (const m of matchesOf(pattern, content)) {
        if (piiValid(entity, m.text)) hits.push({ start: m.start, end: m.end, type: entity, replacement: this.replacement.replaceAll("{entity}", entity), order: rank });
      }
    }
    const [redacted, findings] = applyHits(content, hits, true);
    return verdictOf("redact", redacted, findings, `found ${findingTypes(findings)}`);
  }
}

export const piiRegex = defineProvider({
  port: "Guardrail",
  name: "pii.regex",
  deterministic: true,
  stages: ALL_STAGES,
  settings: {
    properties: {
      entities: { type: "array", minItems: 1, items: { enum: Object.keys(PII_PATTERNS) }, default: Object.keys(PII_PATTERNS) },
      replacement: { type: "string", default: "[{entity}]" },
    },
  },
  create: (s) => new PiiRegex(s.entities as string[], s.replacement as string),
});

// --- secrets.scan -----------------------------------------------------------------------

/** `[type, pattern, ignoreCase]`, in the order ties are broken. */
export const SECRET_PATTERNS: [string, string, boolean][] = [
  ["private_key", "-----BEGIN [A-Z ]*PRIVATE KEY-----[\\s\\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", false],
  ["aws_access_key", "\\b(?:AKIA|ASIA)[0-9A-Z]{16}\\b", false],
  ["github_token", "\\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})", false],
  ["slack_token", "\\bxox[abposr]-[A-Za-z0-9-]{10,}", false],
  ["anthropic_key", "\\bsk-ant-[A-Za-z0-9_-]{20,}", false],
  ["openai_key", "\\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}", false],
  ["google_api_key", "\\bAIza[0-9A-Za-z_-]{35}", false],
  ["jwt", "\\beyJ[A-Za-z0-9_-]{8,}\\.eyJ[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9_-]{8,}", false],
  ["credential_assignment", "\\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token)\\s*[:=]\\s*[\"']?[^\\s\"']{8,}", true],
];

/** Finds credentials: private keys, cloud and API keys, tokens, JWTs, password assignments. */
export class SecretsScan implements Guardrail {
  private readonly patterns: [string, RegExp, number][];

  constructor(
    kinds: readonly string[] | null = null,
    private readonly replacement = "[SECRET]",
  ) {
    this.patterns = SECRET_PATTERNS.flatMap(([kind, pattern, ignoreCase], rank): [string, RegExp, number][] =>
      kinds === null || kinds.includes(kind) ? [[kind, compilePattern(pattern, ignoreCase), rank]] : [],
    );
  }

  check(content: string): GuardResult {
    const hits: Hit[] = [];
    for (const [kind, pattern, rank] of this.patterns) {
      for (const m of matchesOf(pattern, content)) hits.push({ start: m.start, end: m.end, type: kind, replacement: this.replacement, order: rank });
    }
    const [redacted, findings] = applyHits(content, hits);
    return verdictOf("block", redacted, findings, `found ${findingTypes(findings)}`);
  }
}

export const secretsScan = defineProvider({
  port: "Guardrail",
  name: "secrets.scan",
  deterministic: true,
  stages: ALL_STAGES,
  settings: {
    properties: {
      kinds: { anyOf: [{ type: "array", items: { enum: SECRET_PATTERNS.map(([k]) => k) } }, { type: "null" }], default: null },
      replacement: { type: "string", default: "[SECRET]" },
    },
  },
  create: (s) => new SecretsScan(s.kinds as string[] | null, s.replacement as string),
});

// --- injection.heuristic ----------------------------------------------------------------

/** `[type, pattern, weight]`; matched case-insensitively. */
export const INJECTION_PATTERNS: [string, string, number][] = [
  [
    "ignore_instructions",
    "\\b(?:ignore|disregard|forget|override)\\b[^.\\n]{0,40}\\b(?:previous|prior|above|earlier" +
      "|preceding|all|any|your|the|these|those)\\b[^.\\n]{0,20}\\b(?:instructions?|prompts?|rules" +
      "|directions|guidelines)\\b",
    1.0,
  ],
  [
    "reveal_prompt",
    "\\b(?:reveal|show|print|repeat|output|tell me)\\b[^.\\n]{0,30}\\b(?:system prompt" +
      "|hidden (?:prompt|instructions)|your instructions|initial instructions)",
    1.0,
  ],
  [
    "role_override",
    "\\b(?:you are now|from now on,? you are|act as|pretend (?:to be|you are))\\b[^.\\n]{0,40}" +
      "\\b(?:unrestricted|unfiltered|jailbroken|developer mode|DAN" +
      "|no (?:rules|restrictions|limits))",
    1.0,
  ],
  ["fake_system", "(?:<\\|im_start\\|>|<\\|system\\|>|\\[system\\]|###\\s*system\\b|BEGIN SYSTEM PROMPT)", 0.5],
  ["exfiltrate", "\\b(?:send|post|upload|exfiltrate)\\b[^.\\n]{0,40}\\b(?:to|at)\\b[^.\\n]{0,10}https?://", 0.5],
];

/** Scores phrases typical of prompt injection. Cheap, and easy to evade. */
export class InjectionHeuristic implements Guardrail {
  private readonly patterns = INJECTION_PATTERNS.map(([kind, pattern, weight]) => [kind, new RegExp(pattern, "i"), weight] as const);

  constructor(private readonly threshold = 0.5) {}

  check(content: string): GuardResult {
    const findings: Finding[] = [];
    let score = 0;
    for (const [kind, pattern, weight] of this.patterns) {
      const match = pattern.exec(content);
      if (match !== null) {
        const start = codePoints(content.slice(0, match.index)).length;
        findings.push({ type: `injection:${kind}`, start, end: start + codePoints(match[0]).length, score: weight, private: false });
        score += weight;
      }
    }
    score = Math.min(score, 1);
    if (score < this.threshold) return ALLOW;
    return { action: "block", content: null, findings, score, reason: `possible prompt injection (${findingTypes(findings)})` };
  }
}

export const injectionHeuristic = defineProvider({
  port: "Guardrail",
  name: "injection.heuristic",
  deterministic: true,
  stages: ["input", "context", "tool_result"],
  settings: { properties: { threshold: { type: "number", exclusiveMinimum: 0, maximum: 1, default: 0.5 } } },
  create: (s) => new InjectionHeuristic(s.threshold as number),
});

// --- regex.deny -------------------------------------------------------------------------

/** Blocks content matching any of the configured patterns. */
export class RegexDeny implements Guardrail {
  private readonly patterns: RegExp[];

  constructor(
    patterns: readonly string[],
    ignoreCase = false,
    private readonly replacement = "[REDACTED]",
  ) {
    this.patterns = patterns.map((p) => {
      try {
        return compilePattern(p, ignoreCase);
      } catch (error) {
        throw new RangeError(`invalid pattern '${p}': ${(error as Error).message}`);
      }
    });
  }

  check(content: string): GuardResult {
    const hits: Hit[] = [];
    this.patterns.forEach((pattern, index) => {
      for (const m of matchesOf(pattern, content)) {
        if (m.end > m.start) hits.push({ start: m.start, end: m.end, type: `regex:${index}`, replacement: this.replacement, order: index });
      }
    });
    const [redacted, findings] = applyHits(content, hits);
    return verdictOf("block", redacted, findings, "matched a denied pattern");
  }
}

export const regexDeny = defineProvider({
  port: "Guardrail",
  name: "regex.deny",
  deterministic: true,
  stages: ALL_STAGES,
  settings: {
    required: ["patterns"],
    properties: {
      patterns: { type: "array", minItems: 1, items: { type: "string" } },
      ignore_case: { type: "boolean", default: false },
      replacement: { type: "string", default: "[REDACTED]" },
    },
  },
  create: (s) => new RegexDeny(s.patterns as string[], s.ignore_case as boolean, s.replacement as string),
});

// --- size.limit -------------------------------------------------------------------------

/** Flags content over a size; its redaction truncates. Characters are code points. */
export class SizeLimit implements Guardrail {
  constructor(
    private readonly maxChars: number | null,
    private readonly maxBytes: number | null,
  ) {
    if (maxChars === null && maxBytes === null) throw new RangeError("set max_chars or max_bytes");
  }

  check(content: string): GuardResult {
    const chars = codePoints(content);
    let kept = this.maxChars === null ? chars : chars.slice(0, this.maxChars);
    if (this.maxBytes !== null) {
      const encoder = new TextEncoder();
      while (encoder.encode(kept.join("")).length > this.maxBytes) kept = kept.slice(0, -1);
    }
    if (kept.length === chars.length) return ALLOW;
    return {
      action: "block",
      content: kept.join(""),
      findings: [{ type: "size", start: kept.length, end: chars.length, score: null, private: false }],
      reason: "content is over the size limit",
      score: null,
    };
  }
}

export const sizeLimit = defineProvider({
  port: "Guardrail",
  name: "size.limit",
  deterministic: true,
  stages: ALL_STAGES,
  settings: {
    properties: {
      max_chars: { anyOf: [{ type: "integer", exclusiveMinimum: 0 }, { type: "null" }], default: null },
      max_bytes: { anyOf: [{ type: "integer", exclusiveMinimum: 0 }, { type: "null" }], default: null },
    },
  },
  create: (s) => new SizeLimit(s.max_chars as number | null, s.max_bytes as number | null),
});

// --- topic.deny -------------------------------------------------------------------------

/** Flags content that mentions denied topics, by whole-word keywords (case-insensitive). */
export class TopicDeny implements Guardrail {
  private readonly patterns: [string, RegExp, number][];

  constructor(
    topics: Record<string, readonly string[]>,
    private readonly replacement = "[REDACTED]",
  ) {
    this.patterns = Object.entries(topics).flatMap(([topic, keywords], rank) =>
      keywords.map((keyword): [string, RegExp, number] => [topic, compilePattern(`\\b${escapeRegExp(keyword)}\\b`, true), rank]),
    );
  }

  check(content: string): GuardResult {
    const hits: Hit[] = [];
    for (const [topic, pattern, rank] of this.patterns) {
      for (const m of matchesOf(pattern, content)) hits.push({ start: m.start, end: m.end, type: `topic:${topic}`, replacement: this.replacement, order: rank });
    }
    const [redacted, findings] = applyHits(content, hits);
    return verdictOf("block", redacted, findings, `mentions ${findingTypes(findings)}`);
  }
}

export const topicDeny = defineProvider({
  port: "Guardrail",
  name: "topic.deny",
  deterministic: true,
  stages: ["input", "output"],
  settings: {
    required: ["topics"],
    properties: {
      topics: { type: "object", minProperties: 1, additionalProperties: { type: "array", items: { type: "string" } } },
      replacement: { type: "string", default: "[REDACTED]" },
    },
  },
  create: (s) => new TopicDeny(s.topics as Record<string, string[]>, s.replacement as string),
});

// --- grounded.citations -----------------------------------------------------------------

const SENTENCE_END = /(?<=[.!?])\s+|\n+/g;

/** `[start, sentence]` pairs, with code-point starts. */
function sentences(text: string): [number, string][] {
  const found: [number, string][] = [];
  let start = 0;
  for (const match of text.matchAll(SENTENCE_END)) {
    found.push([start, text.slice(start, match.index)]);
    start = match.index + match[0].length;
  }
  found.push([start, text.slice(start)]);
  return found.map(([offset, sentence]) => [codePoints(text.slice(0, offset)).length, sentence]);
}

/**
 * Claims in an answer cite the context the run retrieved (ADR-0032): a context id in
 * square brackets, inside the sentence. Proposes `repair` when fewer than
 * `min_supported` of the sentences of at least `min_words` words cite something, or
 * when a citation names an id the run didn't keep.
 */
export class GroundedCitations implements Guardrail {
  private readonly pattern: RegExp;

  constructor(
    private readonly minSupported = 0.9,
    private readonly minWords = 4,
    private readonly requireKnown = true,
    pattern = "\\[([A-Za-z0-9_.:#/-]+)\\]",
  ) {
    this.pattern = new RegExp(pattern, "g");
    if (new RegExp(`${pattern}|`).exec("")!.length < 2) throw new RangeError("the pattern needs a group for the cited id");
  }

  check(content: string): GuardResult {
    const run = currentRun();
    const known = run !== undefined && this.requireKnown ? run.contextIds : undefined;
    const findings: Finding[] = [];
    let considered = 0;
    let supported = 0;
    for (const [start, sentence] of sentences(content)) {
      const cited = [...sentence.matchAll(this.pattern)];
      if (tokens(sentence.replace(this.pattern, " ")).length < this.minWords) continue;
      considered += 1;
      let valid = 0;
      for (const match of cited) {
        if (known === undefined || known.has(match[1] ?? "")) {
          valid += 1;
        } else {
          const at = start + codePoints(sentence.slice(0, match.index)).length;
          findings.push({ type: "unknown_citation", start: at, end: at + codePoints(match[0]).length, score: null, private: false });
        }
      }
      if (valid) supported += 1;
      else findings.push({ type: "uncited_sentence", start, end: start + codePoints(sentence).length, score: null, private: false });
    }
    if (!considered) return ALLOW;
    const share = supported / considered;
    const unknown = findings.filter((f) => f.type === "unknown_citation").length;
    if (share >= this.minSupported && !unknown) return ALLOW;
    let reason = `${supported} of ${considered} sentences cite retrieved context`;
    if (unknown) reason += `; ${unknown} citation(s) name nothing the run retrieved`;
    return { action: "repair", content: null, findings, reason, score: Math.round(share * 1e6) / 1e6 };
  }
}

export const groundedCitations = defineProvider({
  port: "Guardrail",
  name: "grounded.citations",
  deterministic: true,
  stages: ["output"],
  settings: {
    properties: {
      min_supported: { type: "number", minimum: 0, maximum: 1, default: 0.9 },
      min_words: { type: "integer", minimum: 1, default: 4 },
      require_known: { type: "boolean", default: true },
      pattern: { type: "string", default: "\\[([A-Za-z0-9_.:#/-]+)\\]" },
    },
  },
  create: (s) => new GroundedCitations(s.min_supported as number, s.min_words as number, s.require_known as boolean, s.pattern as string),
});

// --- llm.judge --------------------------------------------------------------------------

const JUDGE_SCHEMA = {
  type: "object",
  properties: { pass: { type: "boolean" }, reason: { type: "string" } },
  required: ["pass"],
};

/**
 * Asks a model whether content meets `criteria`. Probabilistic, so it can only make
 * things stricter (R3); its call is governed and budgeted, and its own explanation
 * isn't kept, since it may quote the content (R9).
 */
export class LlmJudge implements Guardrail {
  constructor(
    private readonly criteria: string,
    private readonly model: string | null = null,
  ) {}

  async check(content: string): Promise<GuardResult> {
    const run = currentRun();
    if (run?.generate === undefined) throw new ProviderError("llm.judge needs an active run");
    const response = await run.generate({
      alias: this.model,
      messages: [
        { role: "system", content: `You check content against a rule and answer only with JSON {"pass": true|false, "reason": "..."}. Rule: ${this.criteria}` },
        { role: "user", content },
      ],
      output_schema: JUDGE_SCHEMA,
      temperature: 0,
    });
    let answer: unknown = response.output;
    if (answer === null || answer === undefined) {
      try {
        answer = JSON.parse(response.text ?? "");
      } catch {
        throw new ProviderError("llm.judge got an answer that isn't JSON");
      }
    }
    const verdict = (answer as { pass?: unknown } | null)?.pass;
    if (typeof verdict !== "boolean") throw new ProviderError("llm.judge got an answer without a boolean 'pass'");
    if (verdict) return ALLOW;
    return { action: "block", content: null, reason: "the judge rejected it", findings: [{ type: "judge", private: false }], score: null };
  }
}

export const llmJudge = defineProvider({
  port: "Guardrail",
  name: "llm.judge",
  deterministic: false,
  stages: ["input", "output"],
  settings: {
    required: ["criteria"],
    properties: {
      criteria: { type: "string", minLength: 1 },
      model: { anyOf: [{ type: "string" }, { type: "null" }], default: null },
    },
  },
  create: (s) => new LlmJudge(s.criteria as string, s.model as string | null),
});

/** Every built-in guard provider. */
export const BUILTIN_GUARDS: readonly ProviderDef<Guardrail>[] = [
  piiRegex,
  secretsScan,
  injectionHeuristic,
  regexDeny,
  sizeLimit,
  topicDeny,
  groundedCitations,
  llmJudge,
];
