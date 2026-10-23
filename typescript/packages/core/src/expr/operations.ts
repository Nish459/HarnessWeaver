/**
 * Value operations for the evaluator: equality, comparison, arithmetic and conversions.
 * Errors name types, never values (R9).
 */

import { INT64_MAX, INT64_MIN, typeName, type Key, type Value } from "./values.js";

/** An evaluation error at a position in the expression. */
export class EvalFailure extends Error {
  constructor(
    message: string,
    readonly pos: number,
  ) {
    super(message);
  }
}

const INT_TEXT = /^[+-]?\d+$/;
const DOUBLE_TEXT = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/;

export function isNumber(value: Value): value is bigint | number {
  return typeof value === "bigint" || typeof value === "number";
}

export function int64(value: bigint, pos: number): bigint {
  if (value < INT64_MIN || value > INT64_MAX) throw new EvalFailure("integer overflow", pos);
  return value;
}

/** A double as JavaScript's `Number#toString` writes it, which Python reproduces. */
export function formatDouble(value: number): string {
  return String(value);
}

/** Compare strings by code point, as Python does (not by UTF-16 unit). */
function compareStrings(a: string, b: string): number {
  const x = [...a];
  const y = [...b];
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const p = x[i]!.codePointAt(0)!;
    const q = y[i]!.codePointAt(0)!;
    if (p !== q) return p < q ? -1 : 1;
  }
  return Math.sign(x.length - y.length);
}

export function equals(a: Value, b: Value): boolean {
  if (isNumber(a) && isNumber(b)) return a == b; // bigint == number compares the values
  if (typeName(a) !== typeName(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => equals(x, b[i] as Value));
  if (a instanceof Map && b instanceof Map) {
    if (a.size !== b.size) return false;
    for (const [key, value] of a) {
      const [found, other] = lookup(b, key);
      if (!found || !equals(value, other)) return false;
    }
    return true;
  }
  return a === b;
}

/** Find `key` in a map, comparing keys as values are compared. */
export function lookup(map: Map<Key, Value>, key: Value): [boolean, Value] {
  for (const [candidate, value] of map) if (equals(candidate, key)) return [true, value];
  return [false, null];
}

export function compare(a: Value, b: Value, pos: number): number {
  if (isNumber(a) && isNumber(b)) return (a > b ? 1 : 0) - (a < b ? 1 : 0);
  if (typeof a === "string" && typeof b === "string") return compareStrings(a, b);
  if (typeof a === "boolean" && typeof b === "boolean") return Number(a) - Number(b);
  throw new EvalFailure(`can't compare ${typeName(a)} with ${typeName(b)}`, pos);
}

export function arithmetic(op: string, a: Value, b: Value, pos: number): Value {
  if (op === "+") {
    if (typeof a === "string" && typeof b === "string") return a + b;
    if (Array.isArray(a) && Array.isArray(b)) return [...a, ...b];
  }
  if (!(isNumber(a) && isNumber(b))) throw new EvalFailure(`no operator '${op}' for ${typeName(a)} and ${typeName(b)}`, pos);
  if (typeof a === "bigint" && typeof b === "bigint") {
    if (op === "+") return int64(a + b, pos);
    if (op === "-") return int64(a - b, pos);
    if (op === "*") return int64(a * b, pos);
    if (b === 0n) throw new EvalFailure(op === "/" ? "division by zero" : "modulus by zero", pos);
    // BigInt division truncates toward zero and % takes the dividend's sign, as CEL does.
    return op === "/" ? int64(a / b, pos) : a % b;
  }
  if (op === "%") throw new EvalFailure("'%' needs two ints", pos);
  const x = Number(a);
  const y = Number(b);
  if (op === "+") return x + y;
  if (op === "-") return x - y;
  if (op === "*") return x * y;
  return x / y; // IEEE 754 division, as in CEL and Python's port of it
}

export function toInt(value: Value, pos: number): bigint {
  if (typeof value === "boolean") throw new EvalFailure("int() doesn't accept bool", pos);
  if (typeof value === "bigint") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new EvalFailure("int() needs a finite double", pos);
    return int64(BigInt(Math.trunc(value)), pos);
  }
  if (typeof value === "string" && INT_TEXT.test(value)) return int64(BigInt(value), pos);
  throw new EvalFailure(`int() can't convert ${typeName(value)}`, pos);
}

export function toDouble(value: Value, pos: number): number {
  if (typeof value === "boolean") throw new EvalFailure("double() doesn't accept bool", pos);
  if (typeof value === "bigint" || typeof value === "number") return Number(value);
  if (typeof value === "string" && DOUBLE_TEXT.test(value)) return Number(value);
  throw new EvalFailure(`double() can't convert ${typeName(value)}`, pos);
}

export function toString(value: Value, pos: number): string {
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "bigint") return value.toString();
  if (typeof value === "number") return formatDouble(value);
  throw new EvalFailure(`string() can't convert ${typeName(value)}`, pos);
}

export function matches(text: Value, pattern: Value, pos: number): boolean {
  if (typeof text !== "string" || typeof pattern !== "string") throw new EvalFailure("matches() needs a string and a pattern", pos);
  let regex: RegExp;
  try {
    regex = new RegExp(pattern, "u");
  } catch (error) {
    throw new EvalFailure(`invalid regular expression: ${(error as Error).message}`, pos);
  }
  return regex.test(text);
}

export function size(value: Value, pos: number): bigint {
  if (typeof value === "string") return BigInt([...value].length);
  if (Array.isArray(value)) return BigInt(value.length);
  if (value instanceof Map) return BigInt(value.size);
  throw new EvalFailure(`size() doesn't accept ${typeName(value)}`, pos);
}
