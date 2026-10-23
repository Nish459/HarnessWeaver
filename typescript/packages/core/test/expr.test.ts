/** Runner for the `expr` suite (cel-lite, ADR-0004). */

import { describe, expect, it } from "vitest";
import { ExpressionEvalError, ExpressionSyntaxError } from "../src/errors.js";
import { compileExpression, toHost, typeName } from "../src/expr/index.js";
import { casesOf } from "./fixtures.js";

describe("expr", () => {
  it.each(casesOf("expr"))("%s", (_, c) => {
    const want = c.expect;
    if (want.error === "syntax") {
      expect(() => compileExpression(c.expr)).toThrow(ExpressionSyntaxError);
      return;
    }
    const expression = compileExpression(c.expr);
    if (want.error === "eval") {
      expect(() => expression.evaluate(c.vars ?? {})).toThrow(ExpressionEvalError);
      return;
    }
    const result = expression.evaluate(c.vars ?? {});
    expect(toHost(result)).toStrictEqual(want.value);
    if ("type" in want) expect(typeName(result)).toBe(want.type);
  });
});
