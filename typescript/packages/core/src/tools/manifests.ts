/**
 * Tool manifests (`kind: Tool`, schema `tool-manifest`): the contract between a tool's
 * owner, the security team and the governor (DESIGNS No. 17, S2).
 */

import type { Risk, SideEffect, ToolInfo, ToolSpec } from "../contracts.js";
import { definitionDigest } from "../digests.js";
import { SpecError, ExpressionSyntaxError } from "../errors.js";
import { compileExpression, type Expression } from "../expr/index.js";
import { SCHEMAS } from "../generated/contracts.js";
import type { JsonObject } from "../json.js";
import { validate, withDefaults, type Schema } from "../jsonschema.js";
import { TOOL_POLICY_VARIABLES } from "../policy.js";

export interface OutputPolicy {
  max_bytes?: number | null;
  sanitize?: ("strip_instructions" | "pii_redact")[];
  label?: "untrusted" | "trusted";
}

export interface ToolManifestSpec {
  transport: "native" | "http" | "code" | "mcp";
  description: string;
  input_schema: JsonObject;
  definition_digest?: string | null;
  handler?: string | null;
  url?: string | null;
  server?: string | null;
  side_effect: SideEffect;
  risk: Risk;
  data_access: string[];
  egress: string[];
  scopes: string[];
  tenants: string[];
  enabled: boolean;
  rate_limit?: { per_principal?: string | null; per_tenant?: string | null } | null;
  approval?: { when?: string | null; approver_role?: string | null } | null;
  output: OutputPolicy;
  [key: string]: unknown;
}

export interface ToolManifest {
  apiVersion: "harnessweaver/v1";
  kind: "Tool";
  metadata: { name: string; version?: string | null; owner?: string | null };
  spec: ToolManifestSpec;
}

const RATE = /^\s*([1-9][0-9]*)\s*\/\s*(s|m|h|d)\s*$/;
const RATE_UNITS: Record<string, number> = { s: 1, m: 60, h: 3600, d: 86400 };

/**
 * "10/m" -> [10, 60]: calls allowed per window, and the window in seconds.
 *
 * @throws RangeError for anything but `<count>/<s|m|h|d>`.
 */
export function parseRate(text: string): [number, number] {
  const found = RATE.exec(text);
  if (found === null) throw new RangeError(`rate '${text}' must look like 10/m (per s, m, h or d)`);
  return [Number(found[1]), RATE_UNITS[found[2]!]!];
}

/**
 * Read a manifest document: checked against the `tool-manifest` schema, with its
 * defaults, and with the transport rules the model enforces.
 *
 * @throws SpecError naming the manifest and the problems.
 */
export function parseManifest(document: unknown, where = "tool manifest"): ToolManifest {
  const schema = SCHEMAS["tool-manifest"] as Schema;
  const problems = validate(document, schema);
  if (problems.length) throw new SpecError(`${where}: ${problems.join("; ")}`);
  const manifest = withDefaults(document, schema) as ToolManifest;
  const spec = manifest.spec;
  const fail = (message: string): never => {
    throw new SpecError(`${where} (${manifest.metadata.name}): ${message}`);
  };
  if (spec.transport === "http" && !spec.url) fail("an http tool needs a url");
  if (spec.transport === "code" && (spec.sandbox ?? "none") === "none") fail("a code tool must name a sandbox, such as monty (S4)");
  if (spec.transport !== "code" && (spec.sandbox ?? "none") !== "none") fail("only code tools (transport: code) run in a sandbox");
  if ((spec.transport === "mcp") !== (spec.server !== null && spec.server !== undefined)) fail("an mcp tool names its server, and only an mcp tool does");
  for (const rate of [spec.rate_limit?.per_principal, spec.rate_limit?.per_tenant]) {
    if (rate) {
      try {
        parseRate(rate);
      } catch (error) {
        fail((error as Error).message);
      }
    }
  }
  return manifest;
}

/** The facts policies and middleware decide on. */
export function toolInfo(manifest: ToolManifest): ToolInfo {
  const spec = manifest.spec;
  return {
    name: manifest.metadata.name,
    version: manifest.metadata.version ?? null,
    side_effect: spec.side_effect,
    risk: spec.risk,
    egress: spec.egress,
    data_access: spec.data_access,
    scopes: spec.scopes,
  };
}

/** What a model is told about the tool. */
export function toolSpec(manifest: ToolManifest): ToolSpec {
  return { name: manifest.metadata.name, description: manifest.spec.description, input_schema: manifest.spec.input_schema };
}

/** The digest of what the manifest currently says. */
export function computedDigest(manifest: ToolManifest): string {
  return definitionDigest(manifest.metadata.name, manifest.spec.description, manifest.spec.input_schema);
}

/**
 * A tool as the governor sees it (`info`) and as a model sees it (`spec`). Tools given
 * in code may have no manifest; `digestOk` is false when a pinned digest doesn't match,
 * and then every call is blocked (S2).
 */
export interface ToolDescription {
  info: ToolInfo;
  spec: ToolSpec;
  manifest?: ToolManifest | null;
  digestOk: boolean;
}

/** Describe a tool by its manifest, checking its pinned digest. */
export function describeManifest(manifest: ToolManifest): ToolDescription {
  const pinned = manifest.spec.definition_digest;
  return {
    info: toolInfo(manifest),
    spec: toolSpec(manifest),
    manifest,
    digestOk: pinned === null || pinned === undefined || pinned === computedDigest(manifest),
  };
}

/**
 * Each manifest's compiled `approval.when`.
 *
 * @throws SpecError for an expression that doesn't compile.
 */
export function approvalRules(manifests: readonly ToolManifest[]): Map<string, Expression> {
  const rules = new Map<string, Expression>();
  for (const manifest of manifests) {
    const when = manifest.spec.approval?.when;
    if (!when) continue;
    try {
      rules.set(manifest.metadata.name, compileExpression(when, TOOL_POLICY_VARIABLES));
    } catch (error) {
      if (error instanceof ExpressionSyntaxError) throw new SpecError(`tool ${manifest.metadata.name}: spec.approval.when: ${error.message}`);
      throw error;
    }
  }
  return rules;
}
