/**
 * cel-lite, the built-in expression language (DESIGNS ADR-0004), from the same fixtures
 * as Python (suite `expr`). It never calls `eval` (S4): variables are converted to
 * plain values first.
 *
 *     compileExpression("args.amount_usd > 100").evaluate({ args: { amount_usd: 250 } }) // true
 */

import { ExpressionEvalError } from "../errors.js";
import { evaluate } from "./evaluator.js";
import type { Node } from "./nodes.js";
import { EvalFailure } from "./operations.js";
import { parse } from "./parser.js";
import { ConversionError, fromHost, typeName, type Value } from "./values.js";

export { formatDouble } from "./operations.js";
export { fromHost, toHost, typeName, type Key, type Value } from "./values.js";

/** A compiled cel-lite expression. Compile once, evaluate many times. */
export class Expression {
  constructor(
    readonly source: string,
    private readonly root: Node,
  ) {}

  /**
   * Evaluate against `variables` (plain JSON-like data). Ints come back as `bigint`.
   *
   * @throws ExpressionEvalError if evaluation fails or a variable can't be converted.
   */
  evaluate(variables: Record<string, unknown> = {}): Value {
    let converted: Map<string, Value>;
    try {
      converted = new Map(Object.entries(variables).map(([name, value]) => [name, fromHost(value)]));
    } catch (error) {
      if (error instanceof ConversionError) throw new ExpressionEvalError(error.message, { expression: this.source });
      throw error;
    }
    try {
      return evaluate(this.root, converted);
    } catch (error) {
      if (!(error instanceof EvalFailure)) throw error;
      throw new ExpressionEvalError(`${error.message} at position ${error.pos}`, { expression: this.source, position: error.pos });
    }
  }

  /**
   * Evaluate a predicate.
   *
   * @throws ExpressionEvalError if evaluation fails or the result isn't a bool.
   */
  evaluateBool(variables: Record<string, unknown> = {}): boolean {
    const result = this.evaluate(variables);
    if (typeof result !== "boolean") throw new ExpressionEvalError(`expected a bool result, got ${typeName(result)}`, { expression: this.source });
    return result;
  }
}

/**
 * Compile a cel-lite expression.
 *
 * @param declared If given, the only variable names it may use (a typo fails at load, R4).
 * @throws ExpressionSyntaxError if the expression is invalid.
 */
export function compileExpression(source: string, declared?: Iterable<string>): Expression {
  return new Expression(source, parse(source, declared === undefined ? undefined : new Set(declared)));
}
