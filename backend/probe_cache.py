"""Small thread-safe TTL cache for expensive host probes.

Aggregate inventory endpoints (capabilities, dependencies, system reports,
tools) repeatedly probe the same executables. Keeping those lookups fresh for
a few seconds reduces request latency and avoids the client-side timeout that
previously surfaced as BrokenPipeError on slow hosts. Execution-time probes
still recompute hashes/inodes so integrity checks remain authoritative.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Hashable, TypeVar

T = TypeVar("T")


class TTLCache:
    def __init__(self, ttl: float = 10.0) -> None:
        self.ttl = max(0.5, float(ttl))
        self._lock = threading.RLock()
        self._data: dict[Hashable, tuple[float, T]] = {}

    def get(self, key: Hashable, producer: Callable[[], T]) -> T:
        now = time.monotonic()
        with self._lock:
            cached = self._data.get(key)
            if cached is not None and now - cached[0] < self.ttl:
                return cached[1]
        value = producer()
        with self._lock:
            self._data[key] = (time.monotonic(), value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def invalidate(self, key: Hashable) -> None:
        with self._lock:
            self._data.pop(key, None)
