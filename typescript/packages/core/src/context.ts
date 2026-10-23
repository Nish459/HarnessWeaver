/**
 * Context sources (DESIGNS No. 21, ADR-0030): the built-in `memory` and `passthrough`
 * providers, and the governance every item goes through before `context.after`:
 *
 * 1. ACL re-check: an item whose ACL excludes the run's tenant or principal is dropped,
 *    even if its provider returned it; with `require_acl`, so is an item with no ACL.
 * 2. Labels: the item's source becomes the source's name, and it is untrusted unless the
 *    source is `label: trusted` (S3).
 * 3. Caps: items past `max_items`, then past `max_tokens` (one token per four
 *    characters), are dropped in the order they came.
 *
 * Each drop is a `harness.context` note naming the item's id, never its content (R9).
 */

import type { Acl, ContextItem, Principal } from "./contracts.js";
import type { Envelope } from "./envelope.js";
import { SpecError } from "./errors.js";
import { isObject, type JsonObject } from "./json.js";
import { defineProvider } from "./plugins/provider.js";
import { loadYamlFile } from "./spec/yaml.js";
import { lexicalSimilarity } from "./text.js";
import type { RunTrace } from "./trace.js";

/** The port every context provider implements. */
export interface ContextProvider {
  fetch(query: string, env: Envelope, options?: { limit?: number | null }): Promise<ContextItem[]> | ContextItem[];
}

/** Whether `principal` in `tenant` may see an item with this ACL. */
export function aclAllows(acl: Acl, tenant: string, principal: Principal): boolean {
  if (acl.tenants?.length && !acl.tenants.includes(tenant)) return false;
  if (!acl.principals?.length && !acl.roles?.length) return true;
  return (acl.principals ?? []).includes(principal.id) || (acl.roles ?? []).some((role) => (principal.roles ?? []).includes(role));
}

interface Document {
  id: string;
  content: string;
  acl?: Acl | null;
  metadata?: JsonObject;
}

/** Documents held in memory, searched lexically; it returns only what the run may see. */
export class MemoryContext implements ContextProvider {
  readonly documents: Document[];

  /** @throws SpecError for a missing or malformed documents file, or repeated ids. */
  constructor(documents: readonly Document[] = [], file?: string | null) {
    const all = [...documents];
    if (file) {
      const loaded = loadYamlFile(file);
      if (!isObject(loaded) || !Array.isArray(loaded.documents)) throw new SpecError(`${file} must be a map with a 'documents' list`);
      for (const document of loaded.documents) {
        if (!isObject(document) || typeof document.id !== "string" || typeof document.content !== "string") throw new SpecError(`${file}: each document needs an id and content`);
        all.push(document as unknown as Document);
      }
    }
    const ids = all.map((d) => d.id);
    if (new Set(ids).size !== ids.length) throw new SpecError("context documents must have unique ids");
    this.documents = all;
  }

  fetch(query: string, env: Envelope, options: { limit?: number | null } = {}): ContextItem[] {
    const ranked = this.documents
      .filter((d) => !d.acl || aclAllows(d.acl, env.tenant, env.principal))
      .map((d) => [lexicalSimilarity(query, d.content), d] as const)
      .filter(([score]) => score > 0)
      .sort(([a, x], [b, y]) => b - a || (x.id < y.id ? -1 : x.id > y.id ? 1 : 0));
    const limited = options.limit === null || options.limit === undefined ? ranked : ranked.slice(0, options.limit);
    return limited.map(([score, d]) => ({
      id: d.id,
      content: d.content,
      source: "memory",
      score: Math.round(score * 1e6) / 1e6,
      untrusted: true,
      acl: d.acl ?? null,
      metadata: d.metadata ?? {},
    }));
  }
}

export const memoryContext = defineProvider({
  port: "ContextProvider",
  name: "memory",
  deterministic: true,
  settings: { properties: { documents: { type: "array", default: [] }, file: { anyOf: [{ type: "string" }, { type: "null" }], default: null } } },
  create: (s) => new MemoryContext(s.documents as Document[], s.file as string | null),
});

/** For items the app retrieves itself: governance applies, and fetching returns nothing. */
export const passthroughContext = defineProvider({
  port: "ContextProvider",
  name: "passthrough",
  deterministic: true,
  create: (): ContextProvider => ({ fetch: () => [] }),
});

/** One `context` entry of the spec. */
export interface ContextSourceSettings {
  label?: "untrusted" | "trusted";
  max_items?: number | null;
  max_tokens?: number | null;
  require_acl?: boolean;
}

/** The spec's context sources, with their providers. One per harness. */
export class ContextSources {
  constructor(private readonly sources: ReadonlyMap<string, [ContextSourceSettings, ContextProvider]>) {}

  /**
   * Ask the source's provider; the caller governs what comes back.
   *
   * @throws SpecError for a source the spec doesn't name.
   */
  async fetch(env: Envelope, source: string, query: string, limit?: number | null): Promise<ContextItem[]> {
    const found = this.sources.get(source);
    if (found === undefined) throw new SpecError(`no context source '${source}'; the spec has ${[...this.sources.keys()].sort().join(", ") || "(none)"}`);
    const [settings, provider] = found;
    const limits = [limit, settings.max_items].filter((n): n is number => typeof n === "number");
    return [...(await provider.fetch(query, env, { limit: limits.length ? Math.min(...limits) : null }))];
  }

  /** ACL re-check, labels and caps, in that order; every drop traced. */
  govern(env: Envelope, trace: RunTrace, source: string, items: readonly ContextItem[]): ContextItem[] {
    const settings = this.sources.get(source)?.[0];
    const drop = (item: ContextItem, code: string, why: string): void => {
      trace.note("harness.context", `dropped ${item.id} from ${source}: ${why}`, { hook: "context.after", code, outcome: "block", details: { source, item: item.id } });
    };
    const kept: ContextItem[] = [];
    for (const item of items) {
      if (item.acl && !aclAllows(item.acl, env.tenant, env.principal)) drop(item, "context_acl", "its ACL excludes this run");
      else if (settings?.require_acl && !item.acl) drop(item, "context_acl", "it has no ACL and the source requires one");
      else kept.push({ ...item, source, untrusted: settings ? (settings.label ?? "untrusted") === "untrusted" : (item.untrusted ?? true) });
    }
    if (settings === undefined) return kept;
    const capped: ContextItem[] = [];
    let tokens = 0;
    for (const item of kept) {
      const size = Math.ceil([...item.content].length / 4);
      if (settings.max_items != null && capped.length >= settings.max_items) drop(item, "context_cap", `over max_items (${settings.max_items})`);
      else if (settings.max_tokens != null && tokens + size > settings.max_tokens) drop(item, "context_cap", `over max_tokens (${settings.max_tokens})`);
      else {
        capped.push(item);
        tokens += size;
      }
    }
    return capped;
  }
}
