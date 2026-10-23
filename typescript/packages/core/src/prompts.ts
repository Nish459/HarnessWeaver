/**
 * Versioned prompts, resolved by `name@version` and filled with `{name}` placeholders
 * (ADR-0013). Files live in `prompts.dir` as `<name>@<version>.md` (or `.txt`):
 *
 * - `support_answer@4.1.0` -> exactly that version;
 * - `support_answer@4` -> the file named `@4`, or else the highest `4.x.y`;
 * - `support_answer` -> the highest version, or the unversioned file.
 *
 * There is no template language (R12): `{question}` is replaced, `{{` and `}}` are
 * literal braces, and a missing variable is an error, as with Python's `format_map`.
 */

import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { SpecError } from "./errors.js";
import { Version, VersionRange } from "./semver.js";

const FILE = /^(?<name>[A-Za-z0-9_.-]+?)(?:@(?<version>[A-Za-z0-9.+-]+))?\.(md|txt)$/;
const PLACEHOLDER = /\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}|[{}]/g;

interface Prompt {
  name: string;
  version: string | null;
  path: string;
}

/** A value as a prompt shows it: strings as they are, everything else as JSON. */
function shown(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** Prompts from one directory; files are listed once and read on first use. */
export class PromptStore {
  private index: Map<string, Prompt[]> | undefined;
  private readonly texts = new Map<string, string>();

  constructor(readonly directory: string) {}

  private async prompts(): Promise<Map<string, Prompt[]>> {
    if (this.index === undefined) {
      const index = new Map<string, Prompt[]>();
      let names: string[] = [];
      try {
        names = (await readdir(this.directory)).sort();
      } catch {
        // no prompts directory: no prompts
      }
      for (const file of names) {
        const groups = FILE.exec(file)?.groups;
        if (groups === undefined) continue;
        const prompt = { name: groups.name!, version: groups.version ?? null, path: join(this.directory, file) };
        index.set(prompt.name, [...(index.get(prompt.name) ?? []), prompt]);
      }
      this.index = index;
    }
    return this.index;
  }

  /** @throws SpecError if no file matches. */
  async find(ref: string): Promise<Prompt> {
    const [name = "", wanted = ""] = ref.includes("@") ? [ref.slice(0, ref.indexOf("@")), ref.slice(ref.indexOf("@") + 1)] : [ref, ""];
    const candidates = (await this.prompts()).get(name) ?? [];
    const exact = candidates.find((p) => p.version === (wanted || null));
    if (exact) return exact;
    const versioned = new Map<string, Prompt>();
    const versions: Version[] = [];
    for (const prompt of candidates) {
      try {
        const version = Version.parse(prompt.version ?? "");
        versions.push(version);
        versioned.set(version.toString(), prompt);
      } catch {
        // an unversioned or oddly named file is only found by its exact name
      }
    }
    let best: Version | undefined;
    try {
      best = VersionRange.parse(wanted || "*").maxSatisfying(versions);
    } catch {
      best = undefined;
    }
    const found = best && versioned.get(best.toString());
    if (!found) throw new SpecError(`no prompt '${ref}' in ${this.directory}`, { prompt: ref });
    return found;
  }

  /**
   * Fill in a prompt's `{name}` placeholders.
   *
   * @throws SpecError for a missing prompt, a variable that wasn't given, or a placeholder
   *   that isn't a plain name.
   */
  async render(ref: string, variables: Readonly<Record<string, unknown>>): Promise<string> {
    const prompt = await this.find(ref);
    let text = this.texts.get(prompt.path);
    if (text === undefined) {
      text = await readFile(prompt.path, "utf8");
      this.texts.set(prompt.path, text);
    }
    return text.replace(PLACEHOLDER, (match, name: string | undefined) => {
      if (match === "{{") return "{";
      if (match === "}}") return "}";
      if (name === undefined) throw new SpecError(`prompt ${ref} has a stray '${match}'; write '${match}${match}' for a literal brace`, { prompt: ref });
      if (!(name in variables)) throw new SpecError(`prompt ${ref} needs the variable '${name}'`, { prompt: ref, variable: name });
      return shown(variables[name]);
    });
  }
}
