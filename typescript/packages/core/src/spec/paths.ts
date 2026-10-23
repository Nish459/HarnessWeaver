/**
 * Paths into a spec, as locks, bounds and `spec explain` write them: dotted keys, with
 * `[id]` selecting a keyed-list item (`guardrails.input[base-pii].action`). Ids may
 * contain dots. `*` matches any map key, and `[*]` any item.
 */

/** A keyed-list item, selected by its id. */
export interface Item {
  id: string;
}

export type Segment = string | Item;
export type SpecPath = readonly Segment[];

export const isItem = (segment: Segment): segment is Item => typeof segment !== "string";

/**
 * Parse `a.b[id].c` into segments.
 *
 * @throws RangeError for a malformed path.
 */
export function parsePath(text: string): Segment[] {
  const segments: Segment[] = [];
  let position = 0;
  let expectKey = true;
  while (position < text.length) {
    if (expectKey) {
      let end = position;
      while (end < text.length && !".[]".includes(text[end]!)) end += 1;
      const key = text.slice(position, end).trim();
      if (!key) throw new RangeError(`invalid spec path '${text}': empty key`);
      segments.push(key);
      position = end;
      expectKey = false;
    } else if (text[position] === "[") {
      const close = text.indexOf("]", position);
      if (close === -1 || close === position + 1) throw new RangeError(`invalid spec path '${text}': bad item selector`);
      segments.push({ id: text.slice(position + 1, close) });
      position = close + 1;
    } else if (text[position] === ".") {
      position += 1;
      expectKey = true;
    } else {
      throw new RangeError(`invalid spec path '${text}'`);
    }
  }
  if (expectKey) throw new RangeError(`invalid spec path '${text}': it can't be empty or end with '.'`);
  return segments;
}

/** Format segments as `a.b[id].c`. */
export function formatPath(path: SpecPath): string {
  let text = "";
  for (const segment of path) text += isItem(segment) ? `[${segment.id}]` : text ? `.${segment}` : segment;
  return text;
}

function same(a: Segment, b: Segment): boolean {
  return isItem(a) ? isItem(b) && a.id === b.id : !isItem(b) && a === b;
}

/** Whether `prefix` is `path` or one of its ancestors. */
export function isPrefix(prefix: SpecPath, path: SpecPath): boolean {
  return prefix.length <= path.length && prefix.every((segment, i) => same(segment, path[i]!));
}

/** Whether `path` matches `pattern`, where `*` and `[*]` match one segment. */
export function matches(pattern: SpecPath, path: SpecPath): boolean {
  if (pattern.length !== path.length) return false;
  return pattern.every((want, i) => {
    const have = path[i]!;
    if (isItem(want)) return isItem(have) && (want.id === "*" || want.id === have.id);
    return !isItem(have) && (want === "*" || want === have);
  });
}
