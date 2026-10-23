/**
 * Canonical JSON and digests: the same value gives the same digest in every language
 * (S2 pins tool definitions by digest; approvals match calls by digest).
 *
 * The canonical text is exactly what Python's `json.dumps(sort_keys=True,
 * separators=(",", ":"), ensure_ascii=True)` writes after integral floats become
 * integers: keys sorted by code point, no spaces, non-ASCII escaped as \uXXXX, and
 * numbers in Python's notation (`1e-05`, not JavaScript's `0.00001`).
 */

import { createHash } from "node:crypto";

/** Python's `repr` of a non-integral float, from JavaScript's shortest digits. */
function pythonFloat(value: number): string {
  const [mantissa = "", exponentText = "0"] = value.toExponential().split("e");
  const exponent = Number(exponentText);
  const decimalPoint = exponent + 1;
  if (decimalPoint > -4 && decimalPoint <= 16) return String(value);
  const sign = exponent < 0 ? "-" : "+";
  return `${mantissa}e${sign}${String(Math.abs(exponent)).padStart(2, "0")}`;
}

function numberText(value: number): string {
  if (!Number.isFinite(value)) throw new RangeError("JSON can't represent NaN or infinity");
  if (Number.isInteger(value)) return BigInt(value).toString();
  return pythonFloat(value);
}

function stringText(value: string, ascii = true): string {
  const text = JSON.stringify(value);
  if (!ascii) return text;
  // Escape DEL and everything above ASCII, as UTF-16 units: Python writes non-BMP
  // characters as surrogate pairs too.
  return text.replace(/[^\x00-\x7e]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

function byCodePoint(a: string, b: string): number {
  const x = [...a];
  const y = [...b];
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const p = x[i]!.codePointAt(0)!;
    const q = y[i]!.codePointAt(0)!;
    if (p !== q) return p - q;
  }
  return x.length - y.length;
}

/** Python's `json.dumps(value, sort_keys=True)` with the given separators. */
function dumps(value: unknown, item: string, key: string, ascii: boolean): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return numberText(value);
  if (typeof value === "bigint") return value.toString();
  if (typeof value === "string") return stringText(value, ascii);
  if (Array.isArray(value)) return `[${value.map((v) => dumps(v, item, key, ascii)).join(item)}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => byCodePoint(a, b));
  return `{${entries.map(([k, v]) => `${stringText(k, ascii)}${key}${dumps(v, item, key, ascii)}`).join(item)}}`;
}

/**
 * The canonical text of a JSON value.
 *
 * @throws RangeError for NaN or infinity, which JSON can't represent.
 */
export function canonicalJson(value: unknown): string {
  return dumps(value, ",", ":", true);
}

/** The canonical text with non-ASCII characters kept as they are (`ensure_ascii=False`). */
export function canonicalUnicode(value: unknown): string {
  return dumps(value, ",", ":", false);
}

/** Python's default `json.dumps(value, sort_keys=True)` text, spaces after `,` and `:`. */
export function pythonJson(value: unknown): string {
  return dumps(value, ", ", ": ", true);
}

/** `sha256:<hex>` of the canonical text. */
export function canonicalDigest(value: unknown): string {
  return `sha256:${createHash("sha256").update(canonicalJson(value), "ascii").digest("hex")}`;
}

/** The digest that pins what a model is told about a tool (S2, rug-pull defense). */
export function definitionDigest(name: string, description: string, inputSchema: unknown): string {
  return canonicalDigest({ name, description, input_schema: inputSchema });
}
