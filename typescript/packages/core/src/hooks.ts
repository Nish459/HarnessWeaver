/**
 * The 13 hook points, their direction, middleware bands and the event payloads (DESIGNS
 * No. 7, fixtures suite `hook_order`). The set is fixed and versioned (R11).
 */

import type { ErrorInfo } from "./errors.js";
import type { JsonValue } from "./json.js";
import type {
  ApprovalDecision,
  ApprovalRequest,
  ContextItem,
  Decision,
  DecisionRequest,
  ModelRequest,
  ModelResponse,
  RunStatus,
  StreamChunk,
  ToolCall,
  ToolInfo,
  ToolResult,
  Usage,
} from "./contracts.js";

export const HOOK_POINTS = [
  "run.start",
  "input.before",
  "route.decide",
  "context.after",
  "model.before",
  "model.after",
  "stream.chunk",
  "tool.before",
  "tool.after",
  "output.before",
  "approval.resolved",
  "run.error",
  "run.end",
] as const;

export type HookPoint = (typeof HOOK_POINTS)[number];
export type Direction = "inbound" | "outbound";

const OUTBOUND = new Set<HookPoint>(["context.after", "model.after", "tool.after", "run.error", "run.end"]);

/** Inbound hooks run outermost-first; outbound hooks run innermost-first. */
export function directionOf(hook: HookPoint): Direction {
  return OUTBOUND.has(hook) ? "outbound" : "inbound";
}

/** Whether a string names a hook point. */
export function isHookPoint(value: string): value is HookPoint {
  return (HOOK_POINTS as readonly string[]).includes(value);
}

/** Middleware priority bands, outermost first. */
export const BANDS = ["baseline", "platform", "app", "task"] as const;
export type Band = (typeof BANDS)[number];

/** A band's rank: baseline 0 ... task 3. */
export function bandRank(band: Band): number {
  return BANDS.indexOf(band);
}

/**
 * Order middleware for one hook: by band (stable, so registration order holds within a
 * band), reversed for outbound hooks.
 */
export function executionOrder<T>(items: readonly T[], hook: HookPoint, band: (item: T) => Band): T[] {
  const ordered = [...items].sort((a, b) => bandRank(band(a)) - bandRank(band(b)));
  if (directionOf(hook) === "outbound") ordered.reverse();
  return ordered;
}

// --- event payloads: raw content in process, never logged before redaction (R9) --------

export interface RunStartEvent {
  hook: "run.start";
  task?: string | null;
  input?: JsonValue;
}
export interface InputEvent {
  hook: "input.before";
  input: JsonValue;
}
export interface RouteEvent {
  hook: "route.decide";
  request: DecisionRequest;
  decision?: Decision | null;
}
export interface ContextEvent {
  hook: "context.after";
  source: string;
  query?: string | null;
  items: ContextItem[];
}
export interface ModelRequestEvent {
  hook: "model.before";
  request: ModelRequest;
}
export interface ModelResponseEvent {
  hook: "model.after";
  request: ModelRequest;
  response: ModelResponse;
}
export interface StreamChunkEvent {
  hook: "stream.chunk";
  request: ModelRequest;
  chunk: StreamChunk;
  text_so_far?: string;
}
export interface ToolCallEvent {
  hook: "tool.before";
  call: ToolCall;
  tool: ToolInfo;
  approval?: ApprovalDecision | null;
}
export interface ToolResultEvent {
  hook: "tool.after";
  call: ToolCall;
  tool: ToolInfo;
  result: ToolResult;
}
export interface OutputEvent {
  hook: "output.before";
  output: JsonValue;
  attempt?: number;
  schema_name?: string | null;
  approval?: ApprovalDecision | null;
}
export interface ApprovalResolvedEvent {
  hook: "approval.resolved";
  request: ApprovalRequest;
  decision: ApprovalDecision;
}
export interface RunErrorEvent {
  hook: "run.error";
  error: ErrorInfo;
  step?: string | null;
}
export interface RunEndEvent {
  hook: "run.end";
  status: RunStatus;
  output?: JsonValue;
  error?: ErrorInfo | null;
  usage?: Usage;
  cost_usd?: number | null;
}

/** Any hook event, discriminated by `hook`. */
export type HookEvent =
  | RunStartEvent
  | InputEvent
  | RouteEvent
  | ContextEvent
  | ModelRequestEvent
  | ModelResponseEvent
  | StreamChunkEvent
  | ToolCallEvent
  | ToolResultEvent
  | OutputEvent
  | ApprovalResolvedEvent
  | RunErrorEvent
  | RunEndEvent;

/** The event type of each hook point. */
export type EventOf<H extends HookPoint> = Extract<HookEvent, { hook: H }>;
