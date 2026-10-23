/**
 * cel-lite values and how host data becomes them.
 *
 * cel-lite tells ints from doubles (`1` vs `1.0`, ADR-0004), and JavaScript numbers
 * can't, so here an int is a `bigint` (64-bit, checked exactly) and a double is a
 * `number`. Maps are `Map`s, since their keys may be ints or bools. Integral numbers in
 * data become ints, as in Python, so data means the same in both languages.
 */

import type { JsonValue } from "../json.js";

export type Key = boolean | bigint | string;
export type Value = boolean | bigint | number | string | null | Value[] | Map<Key, Value>;

export const INT64_MIN = -(2n ** 63n);
export const INT64_MAX = 2n ** 63n - 1n;

/** Host data that cel-lite can't represent. */
export class ConversionError extends Error {}

/** The cel-lite type name of a value, for messages (never the value itself, R9). */
export function typeName(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return "bool";
  if (typeof value === "bigint") return "int";
  if (typeof value === "number") return "double";
  if (typeof value === "string") return "string";
  if (Array.isArray(value)) return "list";
  if (value instanceof Map) return "map";
  return typeof value;
}

/**
 * Convert variables into cel-lite values.
 *
 * @throws ConversionError for types cel-lite doesn't support.
 */
export function fromHost(value: unknown): Value {
  if (value === null || value === undefined) return null;
  switch (typeof value) {
    case "boolean":
    case "string":
      return value;
    case "bigint":
      if (value < INT64_MIN || value > INT64_MAX) throw new ConversionError("integer is outside the 64-bit range");
      return value;
    case "number":
      if (Number.isInteger(value) && value >= -(2 ** 63) && value < 2 ** 63) return BigInt(value);
      return value;
  }
  if (Array.isArray(value)) return value.map(fromHost);
  if (value instanceof Map) {
    const result = new Map<Key, Value>();
    for (const [key, item] of value) {
      if (!["boolean", "bigint", "string"].includes(typeof key)) {
        throw new ConversionError(`map keys must be strings, ints or bools, not ${typeName(key)}`);
      }
      result.set(key as Key, fromHost(item));
    }
    return result;
  }
  if (typeof value === "object") {
    const result = new Map<Key, Value>();
    for (const [key, item] of Object.entries(value)) {
      if (item !== undefined) result.set(key, fromHost(item));
    }
    return result;
  }
  throw new ConversionError(`unsupported value of type ${typeof value}`);
}

/** A cel-lite value as plain JSON: ints become numbers, maps objects. */
export function toHost(value: Value): JsonValue {
  if (typeof value === "bigint") return Number(value);
  if (Array.isArray(value)) return value.map(toHost);
  if (value instanceof Map) {
    const result: { [key: string]: JsonValue } = {};
    for (const [key, item] of value) result[String(key)] = toHost(item);
    return result;
  }
  return value;
}
