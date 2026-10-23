/** The cel-lite syntax tree. */

import type { Value } from "./values.js";

export type Node =
  | { type: "const"; value: Value; pos: number }
  | { type: "ident"; name: string; pos: number }
  | { type: "select"; operand: Node; field: string; pos: number }
  /** `has(operand.field)`. */
  | { type: "presence"; operand: Node; field: string; pos: number }
  | { type: "index"; operand: Node; index: Node; pos: number }
  /** A global function call (no target) or a method call on `target`. */
  | { type: "call"; name: string; target: Node | null; args: Node[]; pos: number }
  | { type: "list"; items: Node[]; pos: number }
  | { type: "map"; entries: [Node, Node][]; pos: number }
  | { type: "unary"; op: string; operand: Node; pos: number }
  | { type: "binary"; op: string; left: Node; right: Node; pos: number }
  | { type: "conditional"; condition: Node; then: Node; otherwise: Node; pos: number }
  /** A macro such as `target.exists(var, body)`. */
  | { type: "comprehension"; macro: string; target: Node; var: string; body: Node; pos: number };

/** cel-lite's limits, functions, methods, macros and reserved words. */
export const MAX_LENGTH = 10_000;
export const MAX_DEPTH = 64;
export const GLOBAL_FUNCTIONS: Record<string, number> = { size: 1, int: 1, double: 1, string: 1, matches: 2 };
export const METHODS: Record<string, number> = { size: 0, startsWith: 1, endsWith: 1, contains: 1, matches: 1 };
export const MACROS = new Set(["exists", "all", "exists_one", "map", "filter"]);
export const RELATIONS = new Set(["==", "!=", "<", "<=", ">", ">="]);
export const RESERVED = new Set([
  "as", "break", "const", "continue", "else", "for", "function", "if", "import", "let",
  "loop", "package", "namespace", "return", "var", "void", "while",
]);
