"""Small, dependency-free in-process rate limiters.

They protect expensive endpoints (OCR, analysis, generation) from accidental or
malicious bursts. They are intentionally in-process: with several workers each
process enforces its own budget, so the effective limit is multiplied by the
number of workers. That limitation is documented in docs/OPERACIONES_V1.md.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Tuple


class SlidingWindowLimiter:
    """Allow at most ``max_events`` events per key inside ``window_seconds``."""

    def __init__(self, max_events: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.max_events = max(1, int(max_events))
        self.window_seconds = max(0.001, float(window_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._events: Dict[str, Deque[float]] = {}

    def _prune(self, key: str, now: float) -> Deque[float]:
        events = self._events.setdefault(key, deque())
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def check(self, key: str) -> Tuple[bool, float]:
        """Register an attempt. Returns (allowed, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            events = self._prune(str(key), now)
            if len(events) >= self.max_events:
                retry_after = max(0.0, self.window_seconds - (now - events[0]))
                return False, retry_after
            events.append(now)
            if len(self._events) > 1000:
                self._events = {k: v for k, v in self._events.items() if v}
            return True, 0.0

    def reset(self, key: str) -> None:
        """Clear the counter for a key (e.g. after a successful login)."""
        with self._lock:
            self._events.pop(str(key), None)


class DailyCounter:
    """Per-key daily counter that resets on the UTC date boundary."""

    def __init__(self, limit: int, clock: Callable[[], float] = time.time):
        self.limit = max(1, int(limit))
        self._clock = clock
        self._lock = threading.Lock()
        self._day = ""
        self._counts: Dict[str, int] = {}

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self._clock()))

    def take(self, key: str) -> bool:
        """Consume one unit, returning False when the daily budget is exhausted."""
        day = self._today()
        with self._lock:
            if day != self._day:
                self._day = day
                self._counts = {}
            used = self._counts.get(str(key), 0)
            if used >= self.limit:
                return False
            self._counts[str(key)] = used + 1
            return True

    def remaining(self, key: str) -> int:
        day = self._today()
        with self._lock:
            if day != self._day:
                return self.limit
            return max(0, self.limit - self._counts.get(str(key), 0))


class ConcurrencyGate:
    """Bound the number of simultaneous expensive operations in this process."""

    def __init__(self, slots: int):
        self.slots = max(1, int(slots))
        self._semaphore = threading.BoundedSemaphore(self.slots)

    def acquire(self, timeout: float = 0.0) -> bool:
        return self._semaphore.acquire(timeout=max(0.0, float(timeout)))

    def release(self) -> None:
        self._semaphore.release()
