import asyncio
import time

from .config import RATE_LIMIT, RATE_PERIOD


class RateLimiter:
    """Async-safe sliding-window rate limiter.

    Tracks timestamps of recent requests and sleeps when the window is full.
    The lock is released during sleep so other coroutines aren't blocked.
    """

    def __init__(self, limit: int = RATE_LIMIT, period: int = RATE_PERIOD):
        self._limit = limit
        self._period = period
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.time()
                self._timestamps = [t for t in self._timestamps if now - t < self._period]

                if len(self._timestamps) < self._limit:
                    self._timestamps.append(time.time())
                    return

                # Calculate how long to wait, but release lock before sleeping
                sleep_time = self._period - (now - self._timestamps[0])

            # Sleep outside the lock so other coroutines can proceed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            # Loop back to re-acquire lock and re-check
