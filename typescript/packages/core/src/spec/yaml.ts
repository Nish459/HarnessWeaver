/**
 * Reading spec files as YAML 1.2 with the core schema, the same as Python (ADR-0017):
 * only `true`/`false` are booleans, no implicit dates, `012` is decimal, and a repeated
 * key is an error rather than silently keeping the last one.
 */

import { readFileSync } from "node:fs";
import { parse } from "yaml";
import { SpecError } from "../errors.js";

/**
 * Parse YAML 1.2 text.
 *
 * @throws SpecError if the text isn't valid YAML or repeats a key.
 */
export function loadYaml(text: string, source = "<string>"): unknown {
  try {
    return parse(text, { version: "1.2", schema: "core", uniqueKeys: true, merge: false });
  } catch (error) {
    throw new SpecError(`${source}: invalid YAML: ${(error as Error).message.split("\n")[0]}`, { source });
  }
}

/** Parse a YAML file. */
export function loadYamlFile(path: string): unknown {
  let text: string;
  try {
    text = readFileSync(path, "utf8");
  } catch {
    throw new SpecError(`can't read ${path}`, { source: path });
  }
  return loadYaml(text, path);
}
