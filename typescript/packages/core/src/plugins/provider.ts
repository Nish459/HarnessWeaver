/**
 * Providers: implementations of a port that a spec selects by name (DESIGNS No. 13).
 *
 * A provider declares its settings as a JSON Schema (the ADR-0026 subset); `build`
 * checks the spec's settings against it, fills in its defaults, and creates the
 * instance, so a typo or a bad value fails when the harness loads (R4, C11).
 */

import { SpecError } from "../errors.js";
import { checkSchema, validate, type Schema } from "../jsonschema.js";
import { isObject } from "../json.js";
import { checkName } from "./names.js";

export type Port = "Guardrail" | "PolicyEngine" | "Decider" | "Evaluator" | "ModelProvider" | "ContextProvider" | "Embedder";

export interface ProviderDef<T = unknown> {
  readonly kind: "provider";
  readonly port: Port;
  readonly name: string;
  /** Whether the same input always gives the same answer; policy engines must be (R3). */
  readonly deterministic: boolean;
  /** The guard stages it can run at; empty means all. */
  readonly stages: readonly string[];
  /** Its settings, as a JSON Schema object; unknown settings are refused. */
  readonly settings: Schema;
  readonly create: (settings: Record<string, unknown>) => T;
}

export interface ProviderOptions<T> {
  port: Port;
  name: string;
  deterministic?: boolean;
  stages?: readonly string[];
  settings?: Schema;
  create: (settings: Record<string, unknown>) => T;
}

/** Declare a provider. */
export function defineProvider<T>(options: ProviderOptions<T>): ProviderDef<T> {
  checkName(options.name);
  const settings: Schema = { type: "object", additionalProperties: false, properties: {}, ...options.settings };
  checkSchema(settings);
  return {
    kind: "provider",
    port: options.port,
    name: options.name,
    deterministic: options.deterministic ?? false,
    stages: options.stages ?? [],
    settings,
    create: options.create,
  };
}

/**
 * Build a provider from the spec's settings for it.
 *
 * @throws SpecError naming the provider and the problems, never the values (R9).
 */
export function buildProvider<T>(provider: ProviderDef<T>, given: Record<string, unknown> = {}): T {
  const problems = validate(given, provider.settings);
  if (problems.length) throw new SpecError(`${provider.port} provider ${provider.name}: ${problems.join("; ")}`);
  const filled: Record<string, unknown> = { ...given };
  const properties = isObject(provider.settings.properties) ? provider.settings.properties : {};
  for (const [name, schema] of Object.entries(properties)) {
    if (!(name in filled) && isObject(schema) && "default" in schema) filled[name] = structuredClone(schema.default);
  }
  try {
    return provider.create(filled);
  } catch (error) {
    if (error instanceof SpecError) throw error;
    throw new SpecError(`${provider.port} provider ${provider.name}: ${(error as Error).message}`);
  }
}
