"""A small in-memory sliding-window rate limiter (per process; resets on restart)."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    """Allow at most ``limit`` hits per key in any ``window`` seconds."""

    def __init__(
        self, limit: int, window: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def hit(self, key: str) -> float | None:
        """Record a hit for ``key``; return seconds to wait if the limit is reached.

        A refused hit is not recorded, so a client that keeps retrying is let in again as
        soon as its oldest counted hit leaves the window.
        """
        now = self._clock()
        with self._lock:
            self._calls += 1
            if self._calls % 1000 == 0:
                self._purge(now)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(0.0, hits[0] + self.window - now)
            hits.append(now)
            return None

    def _purge(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
            del self._hits[key]

    def reset(self) -> None:
        """Forget every hit."""
        with self._lock:
            self._hits.clear()
