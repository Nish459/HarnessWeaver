/** Contract constants and the rules for contributed names (DESIGNS No. 13, fixtures suite `plugins`). */

import { Version } from "../semver.js";

/** The version of the `harnessweaver/v1` contract this core implements (V5). */
export const CONTRACT_VERSION = new Version(1, 0, 0);

/** The namespace of the core's own built-in plugin. */
export const BUILTIN_NAMESPACE = "harnessweaver";

/**
 * Namespaces owned by the built-in plugin; bare names (`direct`) are their own
 * namespace. Other plugins can't claim these.
 */
export const RESERVED_NAMESPACES = new Set([
  BUILTIN_NAMESPACE,
  // runners
  "direct", "session", "workflow",
  // models, state, approvals, context
  "scripted", "memory", "sqlite", "callback", "console", "webhook", "email", "passthrough",
  // policy, routing, validation
  "cel_lite", "rules", "lexical", "semantic", "llm", "pydantic", "json_schema",
  // guardrails
  "pii", "secrets", "regex", "injection", "size", "topic", "grounded",
  // evals
  "exact", "contains", "schema_valid", "field_equals", "numeric_close", "citation_present",
  "guard_fired", "status", "llm_judge",
]);

export const NAMESPACE_PATTERN = /^[a-z][a-z0-9_]*$/;
const NAME = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$/;

/** The contract range a plugin declares by default. */
export const DEFAULT_CONTRACT = ">=1.0,<2";

/** The namespace a name belongs to: the text before the first dot, or the bare name. */
export function namespaceOf(name: string): string {
  return name.split(".", 1)[0] ?? name;
}

/** The namespace of the plugin that owns `name`: reserved namespaces belong to the built-in one. */
export function ownerOf(name: string): string {
  const space = namespaceOf(name);
  return RESERVED_NAMESPACES.has(space) ? BUILTIN_NAMESPACE : space;
}

/** Whether `plugins.allow` permits a namespace. The built-in one always is; no list allows all. */
export function isAllowed(namespace: string, allow: readonly string[] | null | undefined): boolean {
  return allow === null || allow === undefined || namespace === BUILTIN_NAMESPACE || allow.includes(namespace);
}

/** Give a bare contributed name its plugin's namespace; the built-in plugin keeps names as written. */
export function qualify(namespace: string, name: string): string {
  return namespace === BUILTIN_NAMESPACE || name.includes(".") ? name : `${namespace}.${name}`;
}

/** @throws RangeError for a name that isn't lowercase words joined by dots. */
export function checkName(name: string): string {
  if (!NAME.test(name)) throw new RangeError(`invalid name '${name}': use lowercase words joined by dots`);
  return name;
}

/** Why `name` sits outside a plugin's namespace, or undefined if it's fine. */
export function ownershipProblem(namespace: string, name: string): string | undefined {
  const space = namespaceOf(name);
  if (namespace === BUILTIN_NAMESPACE) {
    return RESERVED_NAMESPACES.has(space) ? undefined : `built-in name '${name}' is outside the reserved namespaces`;
  }
  return space === namespace ? undefined : `plugin '${namespace}' contributes '${name}', outside its namespace`;
}

/** @throws RangeError for a namespace a plugin can't use. */
export function checkNamespace(namespace: string): string {
  if (!NAMESPACE_PATTERN.test(namespace)) {
    throw new RangeError(`invalid namespace '${namespace}': use a lowercase identifier such as 'acme'`);
  }
  return namespace;
}
