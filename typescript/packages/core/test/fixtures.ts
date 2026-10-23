/** Loads the language-neutral fixtures in contracts/fixtures/conformance (RULES T4, R11). */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// biome-ignore lint: fixture cases are free-form JSON, each suite reads its own fields.
export type Case = Record<string, any> & { name: string; _file: string };

/** The fixtures folder, found by walking up from this file. */
export const FIXTURES_ROOT = (() => {
  let directory = dirname(fileURLToPath(import.meta.url));
  for (;;) {
    const candidate = join(directory, "contracts", "fixtures", "conformance");
    try {
      if (statSync(candidate).isDirectory()) return candidate;
    } catch {
      // keep walking up
    }
    const parent = dirname(directory);
    if (parent === directory) throw new Error("contracts/fixtures/conformance not found");
    directory = parent;
  }
})();

/** Every suite folder's name. */
export function suites(): string[] {
  return readdirSync(FIXTURES_ROOT)
    .filter((name) => !name.startsWith(".") && statSync(join(FIXTURES_ROOT, name)).isDirectory())
    .sort();
}

/** Every case in a suite, tagged with the file it came from. */
export function loadSuite(suite: string): Case[] {
  const cases: Case[] = [];
  const folder = join(FIXTURES_ROOT, suite);
  for (const file of readdirSync(folder).filter((f) => f.endsWith(".json")).sort()) {
    const document = JSON.parse(readFileSync(join(folder, file), "utf8"));
    if (document.suite !== suite) throw new Error(`${file} declares suite ${document.suite}`);
    for (const item of document.cases) cases.push({ ...item, _file: file });
  }
  if (cases.length === 0) throw new Error(`suite ${suite} has no cases`);
  return cases;
}

/** `[label, case]` pairs for `it.each`. */
export function casesOf(suite: string): [string, Case][] {
  return loadSuite(suite).map((c) => [`${c._file}::${c.name}`, c]);
}
