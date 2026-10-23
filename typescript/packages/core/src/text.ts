/**
 * Text scoring shared by the `lexical` and `semantic` stages and the `memory` context
 * provider (ADR-0029, fixtures suite `routing`).
 *
 * - Tokens are runs of letters and digits, lowercased; everything else separates.
 * - Lexical similarity is the cosine of two texts' token counts.
 * - Hashing embeddings: each token adds 1 and each character trigram of `^token$` adds
 *   0.5, at index `h % dims`, plus when bit 16 of `h` is 0 and minus otherwise, where
 *   `h` is the 32-bit FNV-1a of the UTF-8 bytes of "t:" + token or "c:" + trigram. The
 *   vector is then scaled to length 1 (all zeros stays zeros).
 */

const TOKEN = /[\p{L}\p{N}]+/gu;
const ENCODER = new TextEncoder();

/** The text's tokens, in order. */
export function tokens(text: string): string[] {
  return text.toLowerCase().match(TOKEN) ?? [];
}

function counts(text: string): Map<string, number> {
  const found = new Map<string, number>();
  for (const token of tokens(text)) found.set(token, (found.get(token) ?? 0) + 1);
  return found;
}

/** Cosine of the two texts' token counts: 1 for the same words, 0 for none shared. */
export function lexicalSimilarity(a: string, b: string): number {
  const first = counts(a);
  const second = counts(b);
  if (first.size === 0 || second.size === 0) return 0;
  let dot = 0;
  for (const [token, count] of first) dot += count * (second.get(token) ?? 0);
  const norm = (m: Map<string, number>): number => Math.sqrt([...m.values()].reduce((s, c) => s + c * c, 0));
  return dot / (norm(first) * norm(second));
}

/** 32-bit FNV-1a. */
export function fnv1a32(data: Uint8Array): number {
  let value = 0x811c9dc5;
  for (const byte of data) value = Math.imul(value ^ byte, 0x01000193) >>> 0;
  return value >>> 0;
}

/** A deterministic bag-of-words-and-trigrams vector of length `dims`. */
export function hashingEmbedding(text: string, dims = 256): number[] {
  const vector = new Array<number>(dims).fill(0);
  for (const token of tokens(text)) {
    const marked = [..."^", ...token, ..."$"];
    const features: [string, number][] = [[`t:${token}`, 1]];
    for (let i = 0; i + 3 <= marked.length; i++) features.push([`c:${marked.slice(i, i + 3).join("")}`, 0.5]);
    for (const [feature, weight] of features) {
      const h = fnv1a32(ENCODER.encode(feature));
      vector[h % dims]! += ((h >>> 16) & 1) === 0 ? weight : -weight;
    }
  }
  const length = Math.sqrt(vector.reduce((s, v) => s + v * v, 0));
  return length ? vector.map((v) => v / length) : vector;
}

/** Cosine similarity; 0 when either vector is all zeros. */
export function cosine(a: readonly number[], b: readonly number[]): number {
  let dot = 0;
  for (let i = 0; i < Math.min(a.length, b.length); i++) dot += a[i]! * b[i]!;
  const norm = Math.sqrt(a.reduce((s, x) => s + x * x, 0)) * Math.sqrt(b.reduce((s, y) => s + y * y, 0));
  return norm ? dot / norm : 0;
}
