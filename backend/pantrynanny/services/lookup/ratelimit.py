"""Async token bucket used to keep outgoing provider calls below their published limits."""

import asyncio
import time
from collections.abc import Awaitable, Callable


class TokenBucket:
    """Allows ``rate_per_min`` requests/minute, bursts up to ``burst``.

    ``acquire`` reserves a token even when it has to wait (tokens may go negative), so concurrent
    callers queue fairly. Returns False (reserving nothing) if the wait would exceed ``max_wait_s``.
    """

    def __init__(
        self,
        rate_per_min: float,
        burst: int | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.rate_per_s = max(rate_per_min, 0.001) / 60.0
        self.burst = float(burst if burst is not None else max(1, round(rate_per_min / 4)))
        self._clock = clock
        self._sleep = sleep
        self._tokens = self.burst
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate_per_s)
        self._last = now

    def wait_time(self) -> float:
        self._refill()
        return 0.0 if self._tokens >= 1 else (1 - self._tokens) / self.rate_per_s

    async def acquire(self, max_wait_s: float = 0.0) -> bool:
        wait = self.wait_time()
        if wait > max_wait_s:
            return False
        self._tokens -= 1
        if wait > 0:
            await self._sleep(wait)
        return True


_buckets: dict[tuple[str, float], TokenBucket] = {}


def bucket_for(name: str, rate_per_min: float) -> TokenBucket:
    key = (name, rate_per_min)
    if key not in _buckets:
        _buckets[key] = TokenBucket(rate_per_min)
    return _buckets[key]


def reset_buckets() -> None:
    _buckets.clear()
