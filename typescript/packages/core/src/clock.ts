/** The source of time for everything that makes decisions (RULES C4, T8). */

import { parseDuration } from "./durations.js";

export interface Clock {
  /** The current time, in milliseconds since the epoch (UTC). */
  now(): number;
}

/** The real clock: the one sanctioned read of wall time. */
export class SystemClock implements Clock {
  now(): number {
    return Date.now();
  }
}

/** A clock that only moves when told to. Starts on Monday 2026-01-05 09:00 UTC. */
export class FakeClock implements Clock {
  private current: number;

  constructor(start: number | Date = Date.UTC(2026, 0, 5, 9, 0)) {
    this.current = typeof start === "number" ? start : start.getTime();
  }

  now(): number {
    return this.current;
  }

  /** Move forward by a duration such as "5m" or a number of seconds. */
  advance(delta: string | number): void {
    this.current += parseDuration(delta);
  }

  /** Jump to a moment. */
  set(moment: number | Date): void {
    this.current = typeof moment === "number" ? moment : moment.getTime();
  }
}

/** Whether a moment falls on Saturday or Sunday (UTC). */
export function isWeekend(clock: Clock): boolean {
  const day = new Date(clock.now()).getUTCDay();
  return day === 0 || day === 6;
}

/** An ISO 8601 timestamp, as contracts write times. */
export function isoTime(ms: number): string {
  return new Date(ms).toISOString();
}
