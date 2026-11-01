/**
 * A small JSON Schema (2020-12) validator (ADR-0026), the same subset as Python's.
 *
 * Supported: `type`, `enum`, `const`; objects (`properties`, `required`,
 * `additionalProperties`, `minProperties`, `maxProperties`); arrays (`items`, `minItems`,
 * `maxItems`, `uniqueItems`); strings (`minLength`, `maxLength`, `pattern`, searched);
 * numbers (`minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `multipleOf`);
 * `allOf`, `anyOf`, `oneOf`, `not`; and `$ref` to `#/$defs/<name>`. Annotations are
 * ignored; any other keyword fails `checkSchema`, so a schema never checks less than it
 * says (R4). Problems name locations and rules, never values (R9).
 *
 * `propertyNames` is accepted too, for validating specs against their own schemas.
 */

import { canonicalJson } from "./digests.js";
import { isObject } from "./json.js";

const ANNOTATIONS = new Set([
  "$schema", "$id", "$comment", "$defs", "definitions", "title", "description", "default", "examples",
  "format", "deprecated", "readOnly", "writeOnly", "contentMediaType", "contentEncoding",
]);
const KEYWORDS = new Set([
  "type", "enum", "const", "properties", "required", "additionalProperties", "minProperties", "maxProperties",
  "items", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern", "minimum", "maximum",
  "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "allOf", "anyOf", "oneOf", "not", "$ref",
]);
const TYPES = new Set(["object", "array", "string", "integer", "number", "boolean", "null"]);

export type Schema = { [key: string]: unknown };

/** A schema that is malformed or uses a keyword outside the supported subset. */
export class SchemaError extends Error {
  override name = "SchemaError";
}

const where = (path: string): string => path || "(root)";
const isNumber = (value: unknown): value is number => typeof value === "number";
const own = (object: object, key: string): boolean => Object.hasOwn(object, key); // `in` also finds Object.prototype's names

function typeMatches(name: string, value: unknown): boolean {
  switch (name) {
    case "object":
      return isObject(value);
    case "array":
      return Array.isArray(value);
    case "string":
      return typeof value === "string";
    case "boolean":
      return typeof value === "boolean";
    case "null":
      return value === null;
    case "number":
      return isNumber(value) && Number.isFinite(value); // as in JSON, and as in Python's spec models
    default: // integer: a number with no fractional part
      return isNumber(value) && Number.isInteger(value);
  }
}

function schemaAt(root: Schema, ref: string, path: string): Schema {
  for (const prefix of ["#/$defs/", "#/definitions/"]) {
    if (ref.startsWith(prefix)) {
      const defs = root[prefix.slice(2, -1)];
      const target = isObject(defs) ? defs[ref.slice(prefix.length)] : undefined;
      if (isObject(target)) return target;
    }
  }
  throw new SchemaError(`${where(path)}: $ref '${ref}' must name a definition in #/$defs`);
}

function compiles(pattern: string): boolean {
  try {
    new RegExp(pattern, "u");
    return true;
  } catch {
    return false;
  }
}

/**
 * Check that a schema is well formed and uses only the supported keywords.
 *
 * @throws SchemaError naming the first problem's location.
 */
export function checkSchema(schema: Schema, root: Schema = schema, path = ""): void {
  for (const [key, value] of Object.entries(schema)) {
    const at = path ? `${path}.${key}` : key;
    if (ANNOTATIONS.has(key)) {
      if ((key === "$defs" || key === "definitions") && isObject(value)) {
        for (const [name, sub] of Object.entries(value)) checkSub(sub, root, `${at}.${name}`);
      }
      continue;
    }
    if (key === "propertyNames") {
      checkSub(value, root, at);
      continue;
    }
    if (!KEYWORDS.has(key)) throw new SchemaError(`${at}: keyword '${key}' isn't supported`);
    switch (key) {
      case "type": {
        const names = Array.isArray(value) ? value : [value];
        if (names.length === 0 || !names.every((n) => typeof n === "string" && TYPES.has(n))) throw new SchemaError(`${at}: unknown type`);
        break;
      }
      case "pattern":
        if (typeof value !== "string") throw new SchemaError(`${at}: must be a string`);
        if (!compiles(value)) throw new SchemaError(`${at}: isn't a valid regular expression`);
        break;
      case "properties":
        if (!isObject(value)) throw new SchemaError(`${at}: must be an object`);
        for (const [name, sub] of Object.entries(value)) checkSub(sub, root, `${at}.${name}`);
        break;
      case "items":
      case "not":
        checkSub(value, root, at);
        break;
      case "additionalProperties":
        if (value !== true && value !== false) checkSub(value, root, at);
        break;
      case "allOf":
      case "anyOf":
      case "oneOf":
        if (!Array.isArray(value) || value.length === 0) throw new SchemaError(`${at}: must be a non-empty list of schemas`);
        value.forEach((sub, index) => checkSub(sub, root, `${at}[${index}]`));
        break;
      case "$ref":
        if (typeof value !== "string") throw new SchemaError(`${at}: must be a string`);
        schemaAt(root, value, at);
        break;
      case "required":
        if (!Array.isArray(value) || !value.every((n) => typeof n === "string")) throw new SchemaError(`${at}: must be a list of names`);
        break;
      case "enum":
        if (!Array.isArray(value)) throw new SchemaError(`${at}: must be a list`);
        break;
      case "multipleOf":
        if (!isNumber(value) || value <= 0) throw new SchemaError(`${at}: must be a positive number`);
        break;
      case "const":
      case "uniqueItems":
        break;
      default:
        if (!isNumber(value)) throw new SchemaError(`${at}: must be a number`);
    }
  }
}

function checkSub(value: unknown, root: Schema, path: string): void {
  if (typeof value === "boolean") return;
  if (!isObject(value)) throw new SchemaError(`${where(path)}: must be a schema (an object or a boolean)`);
  checkSchema(value, root, path);
}

/** Check `value` against `schema` (which passed `checkSchema`); the problems, empty when valid. */
export function validate(value: unknown, schema: Schema): string[] {
  const problems: string[] = [];
  check(value, schema, schema, "", problems);
  return problems;
}

function check(value: unknown, schema: unknown, root: Schema, path: string, problems: string[]): void {
  if (schema === true) return;
  if (schema === false) {
    problems.push(`${where(path)}: isn't allowed`);
    return;
  }
  if (!isObject(schema)) return;
  const at = where(path);
  if (typeof schema.$ref === "string") check(value, schemaAt(root, schema.$ref, path), root, path, problems);
  if (schema.type !== undefined) {
    const names = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!names.some((n) => typeof n === "string" && typeMatches(n, value))) {
      problems.push(`${at}: must be ${names.join(" or ")}`);
      return;
    }
  }
  if ("const" in schema && canonicalJson(value) !== canonicalJson(schema.const)) problems.push(`${at}: must be the constant value`);
  if (Array.isArray(schema.enum) && !schema.enum.map(canonicalJson).includes(canonicalJson(value))) {
    problems.push(`${at}: must be one of the allowed values`);
  }
  if (isObject(value)) checkObject(value, schema, root, path, problems);
  else if (Array.isArray(value)) checkArray(value, schema, root, path, problems);
  else if (typeof value === "string") checkString(value, schema, at, problems);
  else if (isNumber(value)) checkNumber(value, schema, at, problems);
  checkComposition(value, schema, root, path, problems);
}

function checkObject(value: { [key: string]: unknown }, schema: Schema, root: Schema, path: string, problems: string[]): void {
  const at = where(path);
  const known = isObject(schema.properties) ? schema.properties : {};
  for (const name of Array.isArray(schema.required) ? schema.required : []) {
    if (typeof name === "string" && !own(value, name)) problems.push(`${path ? `${path}.${name}` : name}: is required`);
  }
  const extra = schema.additionalProperties ?? true;
  for (const [name, item] of Object.entries(value)) {
    const child = path ? `${path}.${name}` : name;
    if (schema.propertyNames !== undefined) check(name, schema.propertyNames, root, child, problems);
    if (own(known, name)) check(item, known[name], root, child, problems);
    else if (extra === false) problems.push(`${child}: isn't an allowed property`);
    else check(item, extra, root, child, problems);
  }
  const count = Object.keys(value).length;
  if (isNumber(schema.minProperties) && count < schema.minProperties) problems.push(`${at}: must have at least ${schema.minProperties} properties`);
  if (isNumber(schema.maxProperties) && count > schema.maxProperties) problems.push(`${at}: must have at most ${schema.maxProperties} properties`);
}

function checkArray(value: unknown[], schema: Schema, root: Schema, path: string, problems: string[]): void {
  const at = where(path);
  if (schema.items !== undefined) value.forEach((item, index) => check(item, schema.items, root, `${path}[${index}]`, problems));
  if (isNumber(schema.minItems) && value.length < schema.minItems) problems.push(`${at}: must have at least ${schema.minItems} items`);
  if (isNumber(schema.maxItems) && value.length > schema.maxItems) problems.push(`${at}: must have at most ${schema.maxItems} items`);
  if (schema.uniqueItems === true) {
    const texts = value.map(canonicalJson);
    if (new Set(texts).size !== texts.length) problems.push(`${at}: items must be unique`);
  }
}

function checkString(value: string, schema: Schema, at: string, problems: string[]): void {
  const length = [...value].length;
  if (isNumber(schema.minLength) && length < schema.minLength) problems.push(`${at}: must be at least ${schema.minLength} characters`);
  if (isNumber(schema.maxLength) && length > schema.maxLength) problems.push(`${at}: must be at most ${schema.maxLength} characters`);
  if (typeof schema.pattern === "string" && !new RegExp(schema.pattern, "u").test(value)) problems.push(`${at}: must match the pattern`);
}

const NUMBER_CHECKS: [string, (v: number, l: number) => boolean, string][] = [
  ["minimum", (v, l) => v >= l, "at least"],
  ["maximum", (v, l) => v <= l, "at most"],
  ["exclusiveMinimum", (v, l) => v > l, "more than"],
  ["exclusiveMaximum", (v, l) => v < l, "less than"],
];

function checkNumber(value: number, schema: Schema, at: string, problems: string[]): void {
  for (const [key, ok, words] of NUMBER_CHECKS) {
    const limit = schema[key];
    if (isNumber(limit) && !ok(value, limit)) problems.push(`${at}: must be ${words} ${limit}`);
  }
  const step = schema.multipleOf;
  if (isNumber(step)) {
    const quotient = value / step;
    if (Math.abs(quotient - Math.round(quotient)) > 1e-9) problems.push(`${at}: must be a multiple of ${step}`);
  }
}

function passes(value: unknown, schema: unknown, root: Schema, path: string): boolean {
  const found: string[] = [];
  check(value, schema, root, path, found);
  return found.length === 0;
}

function checkComposition(value: unknown, schema: Schema, root: Schema, path: string, problems: string[]): void {
  const at = where(path);
  if (Array.isArray(schema.allOf)) for (const sub of schema.allOf) check(value, sub, root, path, problems);
  if (Array.isArray(schema.anyOf) && !schema.anyOf.some((sub) => passes(value, sub, root, path))) {
    problems.push(`${at}: must match at least one of the anyOf schemas`);
  }
  if (Array.isArray(schema.oneOf) && schema.oneOf.filter((sub) => passes(value, sub, root, path)).length !== 1) {
    problems.push(`${at}: must match exactly one of the oneOf schemas`);
  }
  if ("not" in schema && passes(value, schema.not, root, path)) problems.push(`${at}: must not match the 'not' schema`);
}

/**
 * A copy of `value` with the schema's `default`s filled in for missing properties,
 * recursively, following `$ref` and the object branch of `anyOf`/`oneOf`. This is how
 * a document read from YAML gets the same defaults the Pydantic models give it.
 */
export function withDefaults(value: unknown, schema: unknown, root: Schema = schema as Schema): unknown {
  let node = schema;
  for (let hops = 0; isObject(node) && typeof node.$ref === "string" && hops < 32; hops++) node = schemaAt(root, node.$ref, "");
  if (!isObject(node)) return value;
  for (const key of ["anyOf", "oneOf"] as const) {
    const branches = node[key];
    if (Array.isArray(branches)) {
      const branch = branches.find((b) => passes(value, b, root, ""));
      if (branch !== undefined) return withDefaults(value, branch, root);
    }
  }
  if (Array.isArray(value)) return node.items === undefined ? value : value.map((item) => withDefaults(item, node.items, root));
  if (!isObject(value)) return value;
  const result: { [key: string]: unknown } = {};
  const properties = isObject(node.properties) ? node.properties : {};
  for (const [name, sub] of Object.entries(properties)) {
    if (own(value, name)) continue;
    let target = sub;
    if (isObject(target) && !("default" in target) && typeof target.$ref === "string") target = { ...schemaAt(root, target.$ref, ""), ...target };
    if (isObject(target) && "default" in target) result[name] = withDefaults(structuredClone(target.default), sub, root);
  }
  for (const [name, item] of Object.entries(value)) {
    const sub = own(properties, name) ? properties[name] : node.additionalProperties;
    result[name] = sub === undefined || typeof sub === "boolean" ? item : withDefaults(item, sub, root);
  }
  return result;
}
