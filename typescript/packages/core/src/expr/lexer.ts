/** Tokenizer for cel-lite. */

import { ExpressionSyntaxError } from "../errors.js";

export type TokenKind = "int" | "double" | "string" | "ident" | "op" | "eof";

export interface Token {
  kind: TokenKind;
  text: string;
  pos: number;
  value?: bigint | number | string;
}

const OPERATORS = ["==", "!=", "<=", ">=", "&&", "||", "<", ">", "+", "-", "*", "/", "%", "!", "?", ":", ".", ",", "(", ")", "[", "]", "{", "}"];
const NUMBER = /0[xX][0-9a-fA-F]+|\d+\.\d+(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+|\d+/y;
const IDENT = /[_a-zA-Z][_a-zA-Z0-9]*/y;
const SIMPLE_ESCAPES: Record<string, string> = {
  "\\": "\\", "'": "'", '"': '"', "`": "`", "?": "?",
  a: "\x07", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t", v: "\v",
};
const HEX_ESCAPES: Record<string, number> = { x: 2, u: 4, U: 8 };

export function syntaxError(source: string, pos: number, message: string): ExpressionSyntaxError {
  return new ExpressionSyntaxError(`${message} at position ${pos}`, { expression: source, position: pos });
}

/** Read a string literal starting at `start`; return its value and the end index. */
function readString(source: string, start: number): [string, number] {
  let pos = start;
  const raw = source[pos] === "r" || source[pos] === "R";
  if (raw) pos += 1;
  const quote = source[pos] ?? "";
  if (source.startsWith(quote.repeat(3), pos)) throw syntaxError(source, start, "triple-quoted strings are not supported");
  pos += 1;
  let text = "";
  for (;;) {
    const char = source[pos];
    if (char === undefined || char === "\n") throw syntaxError(source, start, "unterminated string");
    if (char === quote) return [text, pos + 1];
    if (char === "\\" && !raw) {
      const escape = source[pos + 1];
      if (escape === undefined) throw syntaxError(source, start, "unterminated string");
      const simple = SIMPLE_ESCAPES[escape];
      if (simple !== undefined) {
        text += simple;
        pos += 2;
        continue;
      }
      const width = HEX_ESCAPES[escape];
      if (width !== undefined) {
        const digits = source.slice(pos + 2, pos + 2 + width);
        if (digits.length !== width || !/^[0-9a-fA-F]+$/.test(digits)) throw syntaxError(source, pos, `invalid \\${escape} escape`);
        const code = Number.parseInt(digits, 16);
        if (code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) throw syntaxError(source, pos, "escape is not a valid code point");
        text += String.fromCodePoint(code);
        pos += 2 + width;
        continue;
      }
      throw syntaxError(source, pos, `invalid escape \\${escape}`);
    }
    text += char;
    pos += 1;
  }
}

/**
 * Split `source` into tokens, ending with an EOF token.
 *
 * @throws ExpressionSyntaxError on characters or literals cel-lite doesn't accept.
 */
export function tokenize(source: string): Token[] {
  const tokens: Token[] = [];
  let pos = 0;
  const length = source.length;
  while (pos < length) {
    const char = source[pos] ?? "";
    if (" \t\r\n".includes(char)) {
      pos += 1;
      continue;
    }
    if (source.startsWith("//", pos)) {
      const newline = source.indexOf("\n", pos);
      pos = newline === -1 ? length : newline + 1;
      continue;
    }
    if (char === "'" || char === '"' || ((char === "r" || char === "R") && (source[pos + 1] === "'" || source[pos + 1] === '"'))) {
      const [value, end] = readString(source, pos);
      tokens.push({ kind: "string", text: source.slice(pos, end), pos, value });
      pos = end;
      continue;
    }
    if (/[0-9]/.test(char)) {
      NUMBER.lastIndex = pos;
      const text = NUMBER.exec(source)?.[0] ?? char;
      const end = pos + text.length;
      const next = source[end];
      if (next !== undefined && /[A-Za-z0-9_.]/.test(next)) throw syntaxError(source, pos, `invalid number '${source.slice(pos, end + 1)}'`);
      if (text.startsWith("0x") || text.startsWith("0X")) tokens.push({ kind: "int", text, pos, value: BigInt(text) });
      else if (/[.eE]/.test(text)) tokens.push({ kind: "double", text, pos, value: Number(text) });
      else tokens.push({ kind: "int", text, pos, value: BigInt(text) });
      pos = end;
      continue;
    }
    IDENT.lastIndex = pos;
    const ident = IDENT.exec(source);
    if (ident !== null) {
      tokens.push({ kind: "ident", text: ident[0], pos });
      pos += ident[0].length;
      continue;
    }
    const op = OPERATORS.find((candidate) => source.startsWith(candidate, pos));
    if (op === undefined) throw syntaxError(source, pos, `unexpected character '${char}'`);
    tokens.push({ kind: "op", text: op, pos });
    pos += op.length;
  }
  tokens.push({ kind: "eof", text: "", pos: length });
  return tokens;
}
