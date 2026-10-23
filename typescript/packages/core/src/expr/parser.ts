/**
 * Precedence-climbing parser for cel-lite. Precedence, lowest to highest (as in CEL):
 *
 *     c ? a : b          (right-associative)
 *     ||
 *     &&
 *     == != < <= > >= in
 *     + -
 *     * / %
 *     ! -                (prefix)
 *     .field  .method()  [index]  f()
 */

import { ExpressionSyntaxError } from "../errors.js";
import { syntaxError, tokenize, type Token } from "./lexer.js";
import { GLOBAL_FUNCTIONS, MACROS, MAX_DEPTH, MAX_LENGTH, METHODS, RELATIONS, RESERVED, type Node } from "./nodes.js";
import { INT64_MAX, INT64_MIN } from "./values.js";

class Parser {
  private readonly tokens: Token[];
  private index = 0;
  private depth = 0;

  constructor(private readonly source: string) {
    this.tokens = tokenize(source);
  }

  // -- helpers ---------------------------------------------------------------------------

  private error(message: string, pos?: number): ExpressionSyntaxError {
    return syntaxError(this.source, pos ?? this.peek().pos, message);
  }

  private peek(): Token {
    return this.tokens[this.index] as Token;
  }

  private advance(): Token {
    const token = this.peek();
    if (token.kind !== "eof") this.index += 1;
    return token;
  }

  private atOp(...ops: string[]): boolean {
    const token = this.peek();
    return token.kind === "op" && ops.includes(token.text);
  }

  private atIn(): boolean {
    const token = this.peek();
    return token.kind === "ident" && token.text === "in";
  }

  private expectOp(op: string): Token {
    if (!this.atOp(op)) {
      const found = this.peek().text || "end of expression";
      throw this.error(`expected '${op}' but found '${found}'`);
    }
    return this.advance();
  }

  private enter(): void {
    this.depth += 1;
    if (this.depth > MAX_DEPTH) throw this.error(`expression nests deeper than ${MAX_DEPTH} levels`);
  }

  // -- grammar ---------------------------------------------------------------------------

  parse(): Node {
    const node = this.expression();
    if (this.peek().kind !== "eof") throw this.error(`unexpected '${this.peek().text}'`);
    return node;
  }

  private expression(): Node {
    this.enter();
    let condition = this.logicalOr();
    if (this.atOp("?")) {
      const pos = this.advance().pos;
      const then = this.logicalOr();
      this.expectOp(":");
      const otherwise = this.expression();
      condition = { type: "conditional", condition, then, otherwise, pos };
    }
    this.depth -= 1;
    return condition;
  }

  private logicalOr(): Node {
    let left = this.logicalAnd();
    while (this.atOp("||")) {
      const pos = this.advance().pos;
      left = { type: "binary", op: "||", left, right: this.logicalAnd(), pos };
    }
    return left;
  }

  private logicalAnd(): Node {
    let left = this.relation();
    while (this.atOp("&&")) {
      const pos = this.advance().pos;
      left = { type: "binary", op: "&&", left, right: this.relation(), pos };
    }
    return left;
  }

  private relation(): Node {
    let left = this.addition();
    for (;;) {
      if (this.atOp(...RELATIONS)) {
        const token = this.advance();
        left = { type: "binary", op: token.text, left, right: this.addition(), pos: token.pos };
      } else if (this.atIn()) {
        const pos = this.advance().pos;
        left = { type: "binary", op: "in", left, right: this.addition(), pos };
      } else {
        return left;
      }
    }
  }

  private addition(): Node {
    let left = this.multiplication();
    while (this.atOp("+", "-")) {
      const token = this.advance();
      left = { type: "binary", op: token.text, left, right: this.multiplication(), pos: token.pos };
    }
    return left;
  }

  private multiplication(): Node {
    let left = this.unary();
    while (this.atOp("*", "/", "%")) {
      const token = this.advance();
      left = { type: "binary", op: token.text, left, right: this.unary(), pos: token.pos };
    }
    return left;
  }

  private unary(): Node {
    return this.checkedInt(this.prefix());
  }

  private prefix(): Node {
    // Literals are range-checked only after negation is folded in, so the most negative
    // int64, -9223372036854775808, is accepted.
    if (this.atOp("!", "-")) {
      const token = this.advance();
      this.enter();
      const operand = this.prefix();
      this.depth -= 1;
      if (token.text === "-" && operand.type === "const") {
        const value = operand.value;
        if (typeof value === "bigint") return { type: "const", value: -value, pos: token.pos };
        if (typeof value === "number") return { type: "const", value: -value, pos: token.pos };
      }
      return { type: "unary", op: token.text, operand: this.checkedInt(operand), pos: token.pos };
    }
    return this.member();
  }

  private checkedInt(node: Node): Node {
    if (node.type === "const" && typeof node.value === "bigint" && (node.value < INT64_MIN || node.value > INT64_MAX)) {
      throw this.error("integer literal is outside the 64-bit range", node.pos);
    }
    return node;
  }

  private member(): Node {
    let node = this.primary();
    for (;;) {
      if (this.atOp(".")) {
        this.advance();
        const name = this.peek();
        if (name.kind !== "ident") throw this.error("expected a field or method name after '.'");
        this.advance();
        node = this.atOp("(") ? this.methodCall(node, name) : { type: "select", operand: node, field: name.text, pos: name.pos };
      } else if (this.atOp("[")) {
        const pos = this.advance().pos;
        const index = this.expression();
        this.expectOp("]");
        node = { type: "index", operand: node, index, pos };
      } else {
        return node;
      }
    }
  }

  private arguments(): Node[] {
    this.expectOp("(");
    const args: Node[] = [];
    if (!this.atOp(")")) {
      args.push(this.expression());
      while (this.atOp(",")) {
        this.advance();
        args.push(this.expression());
      }
    }
    this.expectOp(")");
    return args;
  }

  private methodCall(target: Node, name: Token): Node {
    const args = this.arguments();
    if (MACROS.has(name.text)) {
      if (args.length !== 2) throw this.error(`${name.text}() takes a variable and an expression`, name.pos);
      const [variable, body] = args as [Node, Node];
      if (variable.type !== "ident") throw this.error(`the first argument of ${name.text}() must be a name`, name.pos);
      return { type: "comprehension", macro: name.text, target, var: variable.name, body, pos: name.pos };
    }
    const arity = METHODS[name.text];
    if (arity === undefined) throw this.error(`unknown method '${name.text}'`, name.pos);
    if (args.length !== arity) throw this.error(`${name.text}() takes ${arity} argument(s)`, name.pos);
    return { type: "call", name: name.text, target, args, pos: name.pos };
  }

  private primary(): Node {
    const token = this.peek();
    if (token.kind === "int" || token.kind === "double" || token.kind === "string") {
      this.advance();
      return { type: "const", value: token.value ?? null, pos: token.pos };
    }
    if (token.kind === "ident") {
      this.advance();
      if (token.text === "true" || token.text === "false") return { type: "const", value: token.text === "true", pos: token.pos };
      if (token.text === "null") return { type: "const", value: null, pos: token.pos };
      if (RESERVED.has(token.text) || token.text === "in") throw this.error(`'${token.text}' is a reserved word`, token.pos);
      if (this.atOp("(")) return this.globalCall(token);
      return { type: "ident", name: token.text, pos: token.pos };
    }
    if (this.atOp("(")) {
      this.advance();
      const node = this.expression();
      this.expectOp(")");
      return node;
    }
    if (this.atOp("[")) return this.listLiteral();
    if (this.atOp("{")) return this.mapLiteral();
    throw this.error(`unexpected '${token.text || "end of expression"}'`);
  }

  private globalCall(name: Token): Node {
    const args = this.arguments();
    if (name.text === "has") {
      const [selection] = args;
      if (args.length !== 1 || selection?.type !== "select") {
        throw this.error("has() takes one field selection, e.g. has(a.b)", name.pos);
      }
      return { type: "presence", operand: selection.operand, field: selection.field, pos: name.pos };
    }
    const arity = GLOBAL_FUNCTIONS[name.text];
    if (arity === undefined) throw this.error(`unknown function '${name.text}'`, name.pos);
    if (args.length !== arity) throw this.error(`${name.text}() takes ${arity} argument(s)`, name.pos);
    return { type: "call", name: name.text, target: null, args, pos: name.pos };
  }

  private listLiteral(): Node {
    const pos = this.advance().pos;
    const items: Node[] = [];
    while (!this.atOp("]")) {
      items.push(this.expression());
      if (!this.atOp(",")) break;
      this.advance();
    }
    this.expectOp("]");
    return { type: "list", items, pos };
  }

  private mapLiteral(): Node {
    const pos = this.advance().pos;
    const entries: [Node, Node][] = [];
    while (!this.atOp("}")) {
      const key = this.expression();
      this.expectOp(":");
      entries.push([key, this.expression()]);
      if (!this.atOp(",")) break;
      this.advance();
    }
    this.expectOp("}");
    return { type: "map", entries, pos };
  }
}

/** Fail on an identifier the expression may not use (R4): a typo fails at load. */
function checkDeclared(node: Node, declared: ReadonlySet<string>, bound: ReadonlySet<string>): void {
  switch (node.type) {
    case "ident":
      if (!bound.has(node.name) && !declared.has(node.name)) {
        throw new ExpressionSyntaxError(`undeclared reference '${node.name}' at position ${node.pos}`, { position: node.pos });
      }
      return;
    case "const":
      return;
    case "select":
    case "presence":
    case "unary":
      return checkDeclared(node.operand, declared, bound);
    case "index":
      checkDeclared(node.operand, declared, bound);
      return checkDeclared(node.index, declared, bound);
    case "call":
      if (node.target !== null) checkDeclared(node.target, declared, bound);
      for (const arg of node.args) checkDeclared(arg, declared, bound);
      return;
    case "list":
      for (const item of node.items) checkDeclared(item, declared, bound);
      return;
    case "map":
      for (const [key, value] of node.entries) {
        checkDeclared(key, declared, bound);
        checkDeclared(value, declared, bound);
      }
      return;
    case "binary":
      checkDeclared(node.left, declared, bound);
      return checkDeclared(node.right, declared, bound);
    case "conditional":
      for (const part of [node.condition, node.then, node.otherwise]) checkDeclared(part, declared, bound);
      return;
    case "comprehension":
      checkDeclared(node.target, declared, bound);
      return checkDeclared(node.body, declared, new Set([...bound, node.var]));
  }
}

/**
 * Parse a cel-lite expression into a syntax tree.
 *
 * @param declared If given, the only variable names the expression may use.
 * @throws ExpressionSyntaxError if the expression is malformed, too long or too deep,
 *   calls an unknown function, or uses an undeclared variable.
 */
export function parse(source: string, declared?: ReadonlySet<string>): Node {
  if (source.length > MAX_LENGTH) throw new ExpressionSyntaxError(`expression is longer than ${MAX_LENGTH} characters`);
  const node = new Parser(source).parse();
  if (declared !== undefined) checkDeclared(node, declared, new Set());
  return node;
}
