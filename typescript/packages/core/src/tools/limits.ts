/**
 * Rate limits for governor step 5: sliding windows per tool and principal or tenant.
 * A call reserves its place before the later steps run, so concurrent calls can't all
 * pass the same check; a call that doesn't go ahead gives its place back. Times come
 * from the run's clock (C4).
 */

export type LimitKey = string;
export type Reservation = [LimitKey, number][];

/** Counts calls per key in sliding windows. One per harness. */
export class RateLimiter {
  private readonly calls = new Map<LimitKey, number[]>();

  /** Reserve one call under every `[key, count, windowSeconds]` limit, or none (undefined). */
  acquire(wanted: readonly [LimitKey, number, number][], nowSeconds: number): Reservation | undefined {
    for (const [key, count, window] of wanted) {
      const calls = this.calls.get(key) ?? [];
      while (calls.length && calls[0]! <= nowSeconds - window) calls.shift();
      this.calls.set(key, calls);
      if (calls.length >= count) return undefined;
    }
    return wanted.map(([key]) => {
      this.calls.get(key)!.push(nowSeconds);
      return [key, nowSeconds];
    });
  }

  /** Give back a reservation for a call that won't run. */
  release(reservation: Reservation): void {
    for (const [key, at] of reservation) {
      const calls = this.calls.get(key);
      const index = calls?.indexOf(at) ?? -1;
      if (calls && index >= 0) calls.splice(index, 1);
    }
  }
}

/** The limiter key for one tool and principal or tenant. */
export function limitKey(tool: string, scope: "principal" | "tenant", id: string): LimitKey {
  return JSON.stringify([tool, scope, id]);
}
