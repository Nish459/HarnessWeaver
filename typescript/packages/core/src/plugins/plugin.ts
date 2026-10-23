/**
 * Plugins (DESIGNS No. 13, ADR-0015). JavaScript has no entry points, so a TypeScript
 * plugin is registered explicitly: a package exports `definePlugin({...})` and the app
 * passes it in, `load("harness.yaml", { plugins: [acme] })`. Registering activates
 * nothing; only names the effective spec references are used (S8), and the org's
 * `plugins.allow` applies to them.
 */

import {
  IncompatibleContract,
  PluginConflict,
  PluginNotAllowed,
  SpecError,
  UnknownProvider,
} from "../errors.js";
import { BUILTIN_PROVIDERS } from "../builtins.js";
import type { MiddlewareDef } from "../middleware.js";
import { Version, VersionRange } from "../semver.js";
import {
  BUILTIN_NAMESPACE,
  checkNamespace,
  CONTRACT_VERSION,
  DEFAULT_CONTRACT,
  isAllowed,
  ownerOf,
  ownershipProblem,
  qualify,
  RESERVED_NAMESPACES,
} from "./names.js";
import type { Port, ProviderDef } from "./provider.js";

export interface Plugin {
  readonly namespace: string;
  readonly version: string;
  readonly contract: string;
  readonly providers: readonly ProviderDef[];
  readonly middleware: readonly MiddlewareDef[];
  /** Profiles it contributes, as YAML text: `profile://<namespace>.<name>`. */
  readonly profiles: Readonly<Record<string, string>>;
}

export interface PluginOptions {
  namespace: string;
  version: string;
  contract?: string;
  providers?: readonly ProviderDef[];
  middleware?: readonly MiddlewareDef[];
  profiles?: Readonly<Record<string, string>>;
}

/**
 * Declare a plugin. Bare names get the plugin's namespace (`banned_words` ->
 * `acme.banned_words`); a name in another namespace is refused.
 *
 * @throws RangeError for a bad namespace, version or contract range, or a name the
 *   plugin doesn't own.
 */
export function definePlugin(options: PluginOptions): Plugin {
  const namespace = checkNamespace(options.namespace);
  Version.parse(options.version);
  const contract = options.contract ?? DEFAULT_CONTRACT;
  VersionRange.parse(contract);
  const own = <T extends { name: string }>(item: T): T => {
    const name = qualify(namespace, item.name);
    const problem = ownershipProblem(namespace, name);
    if (problem) throw new RangeError(problem);
    return { ...item, name };
  };
  return {
    namespace,
    version: options.version,
    contract,
    providers: (options.providers ?? []).map(own),
    middleware: (options.middleware ?? []).map(own),
    profiles: { ...(options.profiles ?? {}) },
  };
}

/** The plugin the core's own providers belong to. */
export function builtinPlugin(): Plugin {
  return { namespace: BUILTIN_NAMESPACE, version: CONTRACT_VERSION.toString(), contract: DEFAULT_CONTRACT, providers: BUILTIN_PROVIDERS, middleware: [], profiles: {} };
}

/** The plugins one harness may use, and name lookup across them (C4: one per harness). */
export class Registry {
  private readonly plugins = new Map<string, Plugin>();

  /**
   * @throws PluginConflict for two plugins with one namespace, SpecError for a plugin
   *   claiming a reserved namespace, IncompatibleContract for a contract range that
   *   doesn't include this core's (V5).
   */
  constructor(
    plugins: readonly Plugin[],
    private readonly allow: readonly string[] | null = null,
  ) {
    for (const plugin of [builtinPlugin(), ...plugins]) {
      if (this.plugins.has(plugin.namespace)) throw new PluginConflict(`two plugins use namespace '${plugin.namespace}'`, { namespace: plugin.namespace });
      if (plugin.namespace !== BUILTIN_NAMESPACE && RESERVED_NAMESPACES.has(plugin.namespace)) {
        throw new SpecError(`plugin namespace '${plugin.namespace}' is reserved for the built-in plugin`, { namespace: plugin.namespace });
      }
      if (!VersionRange.parse(plugin.contract).contains(CONTRACT_VERSION)) {
        throw new IncompatibleContract(`plugin '${plugin.namespace}' supports contract ${plugin.contract}, not ${CONTRACT_VERSION}`, { namespace: plugin.namespace });
      }
      this.plugins.set(plugin.namespace, plugin);
    }
  }

  /** The registered plugins, built-in first. */
  get all(): Plugin[] {
    return [...this.plugins.values()];
  }

  private owner(name: string, what: string): Plugin {
    const owner = ownerOf(name);
    if (!isAllowed(owner, this.allow)) {
      throw new PluginNotAllowed(`plugin namespace '${owner}' isn't in plugins.allow (${[...(this.allow ?? [])].sort().join(", ") || "(none)"})`, { namespace: owner });
    }
    const plugin = this.plugins.get(owner);
    if (plugin === undefined) throw new UnknownProvider(`no ${what} '${name}': plugin '${owner}' isn't registered (pass it to load)`, { name });
    return plugin;
  }

  /**
   * The provider `name` for `port`.
   *
   * @throws UnknownProvider, PluginNotAllowed.
   */
  provider<T = unknown>(port: Port, name: string): ProviderDef<T> {
    const found = this.owner(name, `${port} provider`).providers.find((p) => p.port === port && p.name === name);
    if (found === undefined) throw new UnknownProvider(`no ${port} provider '${name}'`, { name, port });
    return found as ProviderDef<T>;
  }

  /** The middleware `name`; see `provider` for what it throws. */
  middleware(name: string): MiddlewareDef {
    const found = this.owner(name, "middleware").middleware.find((m) => m.name === name);
    if (found === undefined) throw new UnknownProvider(`no middleware '${name}'`, { name });
    return found;
  }
}
