/**
 * Evaluator for cel-lite syntax trees. Semantics follow CEL where they overlap:
 *
 * - `&&` and `||` absorb errors: `error || true` is `true`.
 * - Ints are 64-bit and overflow is an error; int division truncates toward zero.
 * - Mixing ints and doubles gives a double (a documented relaxation, ADR-0004).
 * - Values of different types are never equal; comparing them is an error.
 * - Errors name types and keys, never values (R9).
 */

import type { Node } from "./nodes.js";
import {
  arithmetic,
  compare,
  equals,
  EvalFailure,
  int64,
  lookup,
  matches,
  size,
  toDouble,
  toInt,
  toString,
} from "./operations.js";
import { typeName, type Key, type Value } from "./values.js";

type Scope = ReadonlyMap<string, Value>;

class Evaluator {
  constructor(private readonly variables: ReadonlyMap<string, Value>) {}

  visit(node: Node, scope: Scope): Value {
    switch (node.type) {
      case "const":
        return node.value;
      case "ident": {
        if (scope.has(node.name)) return scope.get(node.name) as Value;
        if (this.variables.has(node.name)) return this.variables.get(node.name) as Value;
        throw new EvalFailure(`undeclared reference '${node.name}'`, node.pos);
      }
      case "select": {
        const target = this.visit(node.operand, scope);
        if (!(target instanceof Map)) throw new EvalFailure(`${typeName(target)} has no field '${node.field}'`, node.pos);
        if (!target.has(node.field)) throw new EvalFailure(`no such key '${node.field}'`, node.pos);
        return target.get(node.field) as Value;
      }
      case "presence": {
        const target = this.visit(node.operand, scope);
        if (!(target instanceof Map)) throw new EvalFailure(`has() needs a map, not ${typeName(target)}`, node.pos);
        return target.has(node.field);
      }
      case "index":
        return this.index(this.visit(node.operand, scope), this.visit(node.index, scope), node.pos);
      case "call": {
        const values = node.args.map((arg) => this.visit(arg, scope));
        if (node.target !== null) values.unshift(this.visit(node.target, scope));
        return this.call(node.name, values, node.pos);
      }
      case "list":
        return node.items.map((item) => this.visit(item, scope));
      case "map": {
        const result = new Map<Key, Value>();
        for (const [keyNode, valueNode] of node.entries) {
          const key = this.visit(keyNode, scope);
          if (!(typeof key === "boolean" || typeof key === "bigint" || typeof key === "string")) {
            throw new EvalFailure(`map keys can't be ${typeName(key)}`, node.pos);
          }
          if (lookup(result, key)[0]) throw new EvalFailure("duplicate map key", node.pos);
          result.set(key, this.visit(valueNode, scope));
        }
        return result;
      }
      case "unary": {
        const value = this.visit(node.operand, scope);
        if (node.op === "!") {
          if (typeof value !== "boolean") throw new EvalFailure(`'!' needs a bool, not ${typeName(value)}`, node.pos);
          return !value;
        }
        if (typeof value === "bigint") return int64(-value, node.pos);
        if (typeof value === "number") return -value;
        throw new EvalFailure(`'-' needs a number, not ${typeName(value)}`, node.pos);
      }
      case "binary":
        if (node.op === "&&" || node.op === "||") return this.logical(node.op, node.left, node.right, scope, node.pos);
        return this.binary(node.op, this.visit(node.left, scope), this.visit(node.right, scope), node.pos);
      case "conditional": {
        const test = this.visit(node.condition, scope);
        if (typeof test !== "boolean") throw new EvalFailure(`'?' needs a bool condition, not ${typeName(test)}`, node.pos);
        return this.visit(test ? node.then : node.otherwise, scope);
      }
      case "comprehension":
        return this.comprehension(node, scope);
    }
  }

  /** CEL's commutative logic: a decisive operand wins even if the other one errors. */
  private logical(op: string, left: Node, right: Node, scope: Scope, pos: number): Value {
    const decisive = op === "||";
    const results: (boolean | EvalFailure)[] = [];
    for (const side of [left, right]) {
      let value: Value;
      try {
        value = this.visit(side, scope);
      } catch (error) {
        if (!(error instanceof EvalFailure)) throw error;
        results.push(error);
        continue;
      }
      if (typeof value !== "boolean") {
        results.push(new EvalFailure(`'${op}' needs bools, not ${typeName(value)}`, pos));
        continue;
      }
      if (value === decisive) return decisive;
      results.push(value);
    }
    for (const result of results) if (result instanceof EvalFailure) throw result;
    return !decisive;
  }

  private binary(op: string, a: Value, b: Value, pos: number): Value {
    switch (op) {
      case "==":
        return equals(a, b);
      case "!=":
        return !equals(a, b);
      case "<":
        return compare(a, b, pos) < 0;
      case "<=":
        return compare(a, b, pos) <= 0;
      case ">":
        return compare(a, b, pos) > 0;
      case ">=":
        return compare(a, b, pos) >= 0;
      case "in":
        if (Array.isArray(b)) return b.some((item) => equals(a, item));
        if (b instanceof Map) return lookup(b, a)[0];
        throw new EvalFailure(`'in' needs a list or map, not ${typeName(b)}`, pos);
      default:
        return arithmetic(op, a, b, pos);
    }
  }

  private index(target: Value, key: Value, pos: number): Value {
    if (Array.isArray(target)) {
      if (typeof key !== "bigint") throw new EvalFailure(`list index must be an int, not ${typeName(key)}`, pos);
      if (key < 0n || key >= BigInt(target.length)) throw new EvalFailure("list index out of range", pos);
      return target[Number(key)] as Value;
    }
    if (target instanceof Map) {
      const [found, value] = lookup(target, key);
      if (!found) throw new EvalFailure("no such key", pos);
      return value;
    }
    throw new EvalFailure(`${typeName(target)} can't be indexed`, pos);
  }

  private call(name: string, args: Value[], pos: number): Value {
    const [first = null, second = null] = args;
    switch (name) {
      case "size":
        return size(first, pos);
      case "int":
        return toInt(first, pos);
      case "double":
        return toDouble(first, pos);
      case "string":
        return toString(first, pos);
      case "matches":
        return matches(first, second, pos);
      case "startsWith":
      case "endsWith":
      case "contains": {
        if (typeof first !== "string" || typeof second !== "string") throw new EvalFailure(`${name}() needs strings`, pos);
        if (name === "startsWith") return first.startsWith(second);
        if (name === "endsWith") return first.endsWith(second);
        return first.includes(second);
      }
      default: // the parser rejects unknown functions
        throw new EvalFailure(`unknown function '${name}'`, pos);
    }
  }

  private comprehension(node: Extract<Node, { type: "comprehension" }>, scope: Scope): Value {
    const target = this.visit(node.target, scope);
    let elements: Value[];
    if (Array.isArray(target)) elements = target;
    else if (target instanceof Map) elements = [...target.keys()];
    else throw new EvalFailure(`${node.macro}() needs a list or map, not ${typeName(target)}`, node.pos);

    const results: (Value | EvalFailure)[] = [];
    for (const element of elements) {
      try {
        results.push(this.visit(node.body, new Map([...scope, [node.var, element]])));
      } catch (error) {
        if (!(error instanceof EvalFailure) || node.macro === "map" || node.macro === "filter") throw error;
        results.push(error);
      }
    }
    if (node.macro === "map") return results.filter((r): r is Value => !(r instanceof EvalFailure));
    for (const result of results) {
      if (!(result instanceof EvalFailure) && typeof result !== "boolean") throw new EvalFailure(`${node.macro}() needs a bool predicate`, node.pos);
    }
    if (node.macro === "filter") return elements.filter((_, i) => results[i] === true);
    if (node.macro === "exists" && results.includes(true)) return true;
    if (node.macro === "all" && results.includes(false)) return false;
    const failure = results.find((r) => r instanceof EvalFailure);
    if (failure instanceof EvalFailure) throw failure;
    if (node.macro === "exists_one") return results.filter((r) => r === true).length === 1;
    return node.macro === "all";
  }
}

/**
 * Evaluate a syntax tree against converted variables.
 *
 * @throws EvalFailure on any evaluation error.
 */
export function evaluate(node: Node, variables: ReadonlyMap<string, Value>): Value {
  return new Evaluator(variables).visit(node, new Map());
}
