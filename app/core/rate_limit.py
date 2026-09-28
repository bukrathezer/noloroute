"""Small in-memory sliding-window rate limiter.

Counts live in each process's memory, so with several Cloud Run instances (max 3) a client can
get up to that many times the limit. That is enough to stop brute-force and cost abuse at this
scale; a shared store (e.g. Redis) would be the next step.
"""

import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

_MAX_KEYS = 10_000  # prune idle keys beyond this so memory stays bounded


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        _ALL_LIMITERS.append(self)

    def retry_after(self, key: str, now: float | None = None) -> float | None:
        """Seconds until `key` may try again, or None if it is under the limit (records nothing)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._current(key, now)
            return hits[0] + self.window - now if len(hits) >= self.limit else None

    def record(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._current(key, now).append(now)
            if len(self._hits) > _MAX_KEYS:
                for k in [k for k, v in self._hits.items() if not v]:
                    del self._hits[k]

    def hit(self, key: str, now: float | None = None) -> float | None:
        """Check and record in one step; returns seconds to wait if the limit is exceeded."""
        now = time.monotonic() if now is None else now
        wait = self.retry_after(key, now)
        if wait is None:
            self.record(key, now)
        return wait

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _current(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits


_ALL_LIMITERS: list[RateLimiter] = []


def reset_all_limiters() -> None:
    """For tests: start every limiter from zero."""
    for limiter in _ALL_LIMITERS:
        limiter.reset()


def client_ip(request: Request) -> str:
    # Behind Cloud Run, uvicorn's --proxy-headers already puts the real client address here.
    return request.client.host if request.client else "unknown"


def too_many_requests(retry_after: float) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many requests, please try again later",
        headers={"Retry-After": str(max(1, round(retry_after)))},
    )


def limit_by_ip(limiter: RateLimiter) -> Callable[[Request], None]:
    """FastAPI dependency factory: count one request per client IP against `limiter`."""

    def dependency(request: Request) -> None:
        wait = limiter.hit(client_ip(request))
        if wait is not None:
            raise too_many_requests(wait)

    return dependency
