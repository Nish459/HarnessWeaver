"""Rate limits for governor step 5: sliding windows per tool and principal or tenant.

A call reserves its place before the governor's later steps run, so concurrent
calls can't all pass the same check; a call that isn't allowed in the end gives
its place back. Times come from the run's injected clock (C4).
"""

from collections import deque
from collections.abc import Sequence

__all__ = ["RateLimiter", "Reservation"]

type Key = tuple[str, str, str]
type Reservation = list[tuple[Key, float]]


class RateLimiter:
    """Counts calls per key in sliding windows. One per harness (C4)."""

    def __init__(self) -> None:
        self._calls: dict[Key, deque[float]] = {}

    def acquire(self, wanted: Sequence[tuple[Key, int, float]], now: float) -> Reservation | None:
        """Reserve one call under every ``(key, count, window_seconds)`` limit, or none.

        Returns ``None`` when any limit is full. Doesn't await, so it is atomic on
        the event loop.
        """
        for key, count, window in wanted:
            calls = self._calls.setdefault(key, deque())
            while calls and calls[0] <= now - window:
                calls.popleft()
            if len(calls) >= count:
                return None
        reservation: Reservation = []
        for key, _, _ in wanted:
            self._calls[key].append(now)
            reservation.append((key, now))
        return reservation

    def release(self, reservation: Reservation) -> None:
        """Give back a reservation for a call that won't run."""
        for key, at in reservation:
            calls = self._calls.get(key)
            if calls is not None and at in calls:
                calls.remove(at)
