/**
 * The wire contracts TypeScript works with, typed as JSON (R7, R11).
 *
 * Field names are the contract's own (snake_case), so these objects are exactly what
 * the JSON Schemas in contracts/schemas describe and what harnessd sends.
 */

import type { ErrorInfo } from "./errors.js";
import type { JsonObject, JsonValue } from "./json.js";

/** Who a run acts for. */
export interface Principal {
  id: string;
  roles?: string[];
  attrs?: JsonObject;
}

/** What kind of data a run has touched (S3). */
export interface Labels {
  data_class?: string | null;
  untrusted_seen?: boolean;
  private_seen?: boolean;
  sources?: string[];
}

/** Per-run limits; `deadline` is in whole milliseconds here and a duration on the wire. */
export interface Budget {
  max_usd?: number | null;
  max_tokens?: number | null;
  max_model_calls?: number | null;
  max_tool_calls?: number | null;
  deadline?: number | null;
}

export type Role = "system" | "user" | "assistant" | "tool";

export interface ToolCall {
  id: string;
  name: string;
  arguments?: JsonObject;
}

export interface Message {
  role: Role;
  content?: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string | null;
  name?: string | null;
  extensions?: JsonObject;
}

export interface ToolSpec {
  name: string;
  description?: string;
  input_schema?: JsonObject;
}

export interface ModelRequest {
  alias?: string | null;
  model?: string | null;
  messages: Message[];
  tools?: ToolSpec[];
  output_schema?: JsonObject | null;
  temperature?: number | null;
  max_tokens?: number | null;
  stream?: boolean;
  metadata?: JsonObject;
}

export interface Usage {
  input_tokens?: number;
  output_tokens?: number;
}

export interface ModelResponse {
  model?: string | null;
  text?: string;
  tool_calls?: ToolCall[];
  output?: JsonValue;
  usage?: Usage;
  cost_usd?: number | null;
  finish_reason?: string | null;
  extensions?: JsonObject;
}

export interface StreamChunk {
  index: number;
  delta?: string;
  usage?: Usage | null;
}

export type SideEffect = "none" | "read" | "write_internal" | "write_external" | "destructive";
export type Risk = "low" | "medium" | "high" | "critical";

/** The facts policies and middleware decide on about a tool. */
export interface ToolInfo {
  name: string;
  version?: string | null;
  side_effect?: SideEffect;
  risk?: Risk;
  egress?: string[];
  data_access?: string[];
  scopes?: string[];
}

export interface ToolResult {
  call_id: string;
  output?: JsonValue;
  is_error?: boolean;
  untrusted?: boolean;
  truncated?: boolean;
}

export interface ToolVerdict {
  decision: "allow" | "require_approval" | "block";
  step: number;
  code?: string | null;
  reason: string;
  approver_role?: string | null;
}

export type DecisionKind = "exact" | "probabilistic" | "abstain" | "default";

export interface Decision {
  kind: DecisionKind;
  choice?: string | null;
  confidence?: number | null;
  reason?: string | null;
  stage?: string | null;
}

export interface DecisionRequest {
  router: string;
  text?: string | null;
  options?: string[];
  state?: JsonObject;
}

export interface Acl {
  tenants?: string[];
  principals?: string[];
  roles?: string[];
}

export interface ContextItem {
  id: string;
  content: string;
  source: string;
  score?: number | null;
  untrusted?: boolean;
  acl?: Acl | null;
  metadata?: JsonObject;
}

export interface ApprovalRequest {
  approval_id: string;
  run_id: string;
  reason: string;
  approver_role?: string | null;
  call?: ToolCall | null;
  tool?: ToolInfo | null;
  requested_at: string;
  expires_at?: string | null;
}

export interface ApprovalDecision {
  approval_id: string;
  decision: "approve" | "reject" | "edit";
  approver: Principal;
  edited_args?: JsonObject | null;
  reason?: string | null;
}

export type GuardAction = "allow" | "redact" | "repair" | "escalate" | "require_approval" | "block" | "log_only";

/** Something a guardrail found; never the raw matched text (R9). */
export interface Finding {
  type: string;
  start?: number | null;
  end?: number | null;
  score?: number | null;
  private?: boolean;
}

export interface GuardResult {
  action: GuardAction;
  content?: string | null;
  reason?: string | null;
  findings?: Finding[];
  score?: number | null;
}

export type RunStatus =
  | "pending"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "blocked"
  | "escalated"
  | "failed"
  | "cancelled";

export type TraceKind = "hook" | "outcome" | "failure" | "note";

export interface TraceEvent {
  seq: number;
  at: string;
  kind: TraceKind;
  source: string;
  hook?: string | null;
  band?: string | null;
  outcome?: string | null;
  modified?: boolean;
  reason?: string | null;
  code?: string | null;
  details?: JsonObject;
}

export interface RunResult {
  run_id: string;
  task?: string | null;
  task_version?: string | null;
  status: RunStatus;
  output?: JsonValue;
  error?: ErrorInfo | null;
  approval?: ApprovalRequest | null;
  usage?: Usage;
  cost_usd?: number | null;
  cost_known?: boolean;
  trace?: TraceEvent[];
  started_at?: string | null;
  ended_at?: string | null;
}
