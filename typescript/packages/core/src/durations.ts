/**
 * Durations written as compact strings: "250ms", "20s", "5m", "1h30m", "1d" (fixtures
 * suite `durations`).
 *
 * TypeScript carries a duration as whole milliseconds. A duration is one or more
 * `<number><unit>` segments, largest unit first and each unit once; numbers may have a
 * fraction, but the total must be whole milliseconds. A bare number means seconds.
 * Durations are never negative.
 */

const UNITS_MS: Record<string, bigint> = { d: 86_400_000n, h: 3_600_000n, m: 60_000n, s: 1_000n, ms: 1n };
const UNIT_ORDER = ["d", "h", "m", "s", "ms"];
const SEGMENT = /(\d+(?:\.\d+)?)(ms|d|h|m|s)/y;

/** The string form's pattern, as the JSON Schema states it. */
export const DURATION_PATTERN = "^(\\d+(\\.\\d+)?(ms|d|h|m|s))+$";

/**
 * `text` (a decimal, maybe in exponent form) times `unit` milliseconds, exactly.
 *
 * Exact decimal arithmetic in BigInt, so 0.1s is 100ms and 1.0005s is refused, the
 * same as Python's Decimal.
 */
function exactMs(text: string, unit: bigint, source: unknown): number {
  const match = /^(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i.exec(text);
  if (match === null) throw new RangeError(`invalid duration ${JSON.stringify(source)}`);
  const digits = (match[1] ?? "") + (match[2] ?? "");
  const scale = (match[2]?.length ?? 0) - Number(match[3] ?? 0);
  let numerator = BigInt(digits) * unit;
  let denominator = 1n;
  if (scale > 0) denominator = 10n ** BigInt(scale);
  else numerator *= 10n ** BigInt(-scale);
  if (numerator % denominator !== 0n) {
    throw new RangeError(`duration ${JSON.stringify(source)} is not a whole number of milliseconds`);
  }
  return Number(numerator / denominator);
}

function parseString(text: string): number {
  if (text === "") throw new RangeError("duration is empty");
  let position = 0;
  let total = 0;
  let lastRank = -1;
  while (position < text.length) {
    SEGMENT.lastIndex = position;
    const match = SEGMENT.exec(text);
    if (match === null) {
      throw new RangeError(`invalid duration ${JSON.stringify(text)}; expected e.g. '250ms', '20s', '1h30m'`);
    }
    const [, number = "", unit = ""] = match;
    const rank = UNIT_ORDER.indexOf(unit);
    if (rank <= lastRank) {
      throw new RangeError(`invalid duration ${JSON.stringify(text)}; units must go from largest to smallest`);
    }
    lastRank = rank;
    total += exactMs(number, UNITS_MS[unit] ?? 1n, text);
    position = SEGMENT.lastIndex;
  }
  return total;
}

/**
 * Parse a duration from a string or a number of seconds into milliseconds.
 *
 * @throws RangeError for anything that isn't a valid, non-negative duration.
 */
export function parseDuration(value: unknown): number {
  if (typeof value === "number") {
    if (!Number.isFinite(value) || value < 0) {
      throw new RangeError(`duration ${value} must be a finite, non-negative number of seconds`);
    }
    return exactMs(String(value), 1000n, value);
  }
  if (typeof value === "string") return parseString(value.trim());
  throw new RangeError(`duration must be a string or a number of seconds, not ${typeof value}`);
}

/** The canonical string form of a duration in milliseconds, e.g. "1h30m" or "0s". */
export function formatDuration(ms: number): string {
  if (!Number.isInteger(ms) || ms < 0) throw new RangeError("duration must be whole, non-negative milliseconds");
  if (ms === 0) return "0s";
  let remaining = BigInt(ms);
  let text = "";
  for (const unit of UNIT_ORDER) {
    const size = UNITS_MS[unit] ?? 1n;
    const count = remaining / size;
    remaining %= size;
    if (count > 0n) text += `${count}${unit}`;
  }
  return text;
}
