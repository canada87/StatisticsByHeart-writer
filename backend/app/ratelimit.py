"""In-memory failed-login limiter. Single worker/process by design (see ADR 0003)."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class LoginLimiter:
    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if not q:
            self._failures.pop(key, None)
            return deque()
        return q

    def retry_after(self, *keys: str) -> int:
        """Seconds to wait if any key is locked out, else 0."""
        now = time.monotonic()
        wait = 0.0
        for key in keys:
            q = self._prune(key, now)
            if len(q) >= self.max_failures:
                wait = max(wait, self.window - (now - q[0]))
        return int(wait) + 1 if wait > 0 else 0

    def fail(self, *keys: str) -> None:
        now = time.monotonic()
        for key in keys:
            self._failures[key].append(now)

    def reset(self, *keys: str) -> None:
        for key in keys:
            self._failures.pop(key, None)
