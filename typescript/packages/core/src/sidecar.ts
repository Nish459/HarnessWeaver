/**
 * The client for harnessd, the sidecar (DESIGNS No. 24, ADR-0038), and the guardrail
 * a `where: sidecar` guard uses: its provider's check runs in harnessd, so a TypeScript
 * app can use a Python-only provider. Requests carry the bearer token (S6). With
 * `HARNESSWEAVER_TEST_MODE=1` the client refuses to call out unless it was given its
 * own `fetch` (R14).
 */

import type { Decision, GuardResult, RunResult, ToolVerdict } from "./contracts.js";
import type { Guardrail } from "./guards/common.js";
import { envelopeJson, type Envelope } from "./envelope.js";
import {
  HarnessError,
  NotFound,
  PolicyDenied,
  ProviderError,
  SpecError,
  ValidationFailed,
  type ErrorInfo,
} from "./errors.js";
import type { JsonObject, JsonValue } from "./json.js";
import type { PolicyDecision, PolicyRequest } from "./policy.js";

export const TEST_MODE_ENV = "HARNESSWEAVER_TEST_MODE";

export interface SidecarOptions {
  /** harnessd's address, e.g. http://127.0.0.1:7070. */
  url: string;
  /** The bearer token; otherwise read from `tokenEnv` on each request. */
  token?: string;
  tokenEnv?: string;
  /** A `fetch` to use instead of the global one (tests, proxies). */
  fetch?: typeof fetch;
  timeoutMs?: number;
}

/** A request's caller: who a check runs for (each check is a one-step session there). */
export interface Caller {
  principal?: string | { id: string; roles?: string[] };
  tenant?: string;
  task?: string | null;
}

/** An `ErrorInfo` answer as the taxonomy error it names. */
function errorOf(info: ErrorInfo): HarnessError {
  const make: Record<string, new (message: string, details?: Record<string, JsonValue>) => HarnessError> = {
    not_found: NotFound,
    spec_invalid: SpecError,
    policy_denied: PolicyDenied,
    validation_failed: ValidationFailed,
  };
  return new (make[info.code] ?? ProviderError)(`harnessd: ${info.message}`, { ...info.details, type: info.type });
}

/** A typed client for every harnessd `/v1` route. */
export class SidecarClient {
  private readonly base: string;

  constructor(private readonly options: SidecarOptions) {
    this.base = options.url.replace(/\/+$/, "");
  }

  private async request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    if (this.options.fetch === undefined && process.env[TEST_MODE_ENV] === "1") throw new ProviderError("test mode: the sidecar client doesn't call out (R14)");
    const token = this.options.token ?? process.env[this.options.tokenEnv ?? "HARNESSD_TOKEN"];
    if (!token) throw new ProviderError(`set ${this.options.tokenEnv ?? "HARNESSD_TOKEN"} to call the sidecar`);
    const send = this.options.fetch ?? fetch;
    let response: Response;
    try {
      response = await send(`${this.base}${path}`, {
        method,
        headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: AbortSignal.timeout(this.options.timeoutMs ?? 10_000),
      });
    } catch (error) {
      throw new ProviderError(`can't reach harnessd (${error instanceof Error ? error.name : typeof error})`);
    }
    const text = await response.text();
    let payload: unknown;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      throw new ProviderError(`harnessd answered HTTP ${response.status} with something that isn't JSON`);
    }
    if (!response.ok) {
      const info = payload as Partial<ErrorInfo> | null;
      if (info && typeof info.code === "string" && typeof info.message === "string") throw errorOf(info as ErrorInfo);
      throw new ProviderError(`harnessd answered HTTP ${response.status}`, { status: response.status });
    }
    return payload as T;
  }

  health(): Promise<{ status: string; harnessd: string; harnessweaver: string }> {
    return this.request("GET", "/v1/health");
  }
  spec(): Promise<{ name: string; api_version: string; tasks: string[]; level: string; required_level: string; spec: JsonObject }> {
    return this.request("GET", "/v1/spec");
  }
  hooks(task?: string): Promise<Record<string, { name: string; band: string; fail_mode: string; timeout_seconds: number | null }[]>> {
    return this.request("GET", task ? `/v1/hooks?task=${encodeURIComponent(task)}` : "/v1/hooks");
  }
  checkStage(stage: "input" | "context" | "output", body: Caller & { content?: JsonValue; source?: string; query?: string; items?: unknown[] }): Promise<RunResult> {
    return this.request("POST", `/v1/guards/${stage}`, body);
  }
  checkProvider(name: string, body: { content: string; envelope: JsonObject; settings?: JsonObject; stage?: string | null }): Promise<GuardResult> {
    return this.request("POST", `/v1/guards/providers/${encodeURIComponent(name)}:check`, body);
  }
  decide(router: string, body: Caller & { text?: string | null; options?: string[]; state?: JsonObject; default?: string | null }): Promise<RunResult & { output?: Decision | null }> {
    return this.request("POST", `/v1/decisions/${encodeURIComponent(router)}`, body);
  }
  evaluatePolicy(request: PolicyRequest): Promise<PolicyDecision> {
    return this.request("POST", "/v1/policy/evaluate", request);
  }
  authorize(tool: string, body: Caller & { args?: JsonObject; labels?: JsonObject }): Promise<ToolVerdict> {
    return this.request("POST", `/v1/tools/${encodeURIComponent(tool)}/authorize`, body);
  }
  sanitize(tool: string, body: Caller & { arguments?: JsonObject; output?: JsonValue; is_error?: boolean }): Promise<RunResult> {
    return this.request("POST", `/v1/tools/${encodeURIComponent(tool)}/sanitize`, body);
  }
  validate(body: Caller & { task: string; output: JsonValue }): Promise<RunResult> {
    return this.request("POST", "/v1/validate", body);
  }
  startRun(body: Caller & { task: string; input?: JsonValue; idempotency_key?: string; budget?: JsonObject; attributes?: Record<string, string> }): Promise<RunResult> {
    return this.request("POST", "/v1/runs", body);
  }
  getRun(runId: string): Promise<RunResult> {
    return this.request("GET", `/v1/runs/${encodeURIComponent(runId)}`);
  }
  answerApproval(runId: string, approvalId: string, body: { decision?: "approve" | "reject" | "edit"; approver: string | { id: string; roles?: string[] }; edited_args?: JsonObject; reason?: string }): Promise<RunResult> {
    return this.request("POST", `/v1/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`, body);
  }
  runEvals(body: { dataset?: JsonObject; file?: string }): Promise<JsonObject> {
    return this.request("POST", "/v1/evals/run", body);
  }
}

/** A guardrail whose check runs in harnessd: what a `where: sidecar` guard uses. */
export class RemoteGuardrail implements Guardrail {
  constructor(
    private readonly client: SidecarClient,
    private readonly name: string,
    private readonly settings: JsonObject,
    private readonly stage: string,
  ) {}

  check(content: string, env: Envelope): Promise<GuardResult> {
    return this.client.checkProvider(this.name, { content, envelope: envelopeJson(env), settings: this.settings, stage: this.stage });
  }
}
