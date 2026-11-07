"""A small in-process sliding-window limiter for the public portal endpoints.

One process is enough while this runs as a single Railway service. If it is ever scaled out, the limits become
per instance; move the counters to Redis then. Client addresses come from X-Forwarded-For (uvicorn is run with
--proxy-headers), which a caller can spoof, so the exchange endpoint also has a global limit that spoofing can't dodge,
and writes are limited per link, not per address.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window_seconds, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 10_000:  # forget keys with no recent hits so the table can't grow without bound
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
                    del self._hits[k]
            return True

    def retry_after(self, key: str) -> int:
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return 1
            return max(1, int(self.window - (self.clock() - q[0])) + 1)
