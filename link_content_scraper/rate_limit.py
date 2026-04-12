import asyncio
import time

from .config import RATE_LIMIT, RATE_PERIOD


class RateLimiter:
    """Async-safe sliding-window rate limiter.

    Tracks timestamps of recent requests and sleeps when the window is full.
    """

    def __init__(self, limit: int = RATE_LIMIT, period: int = RATE_PERIOD):
        self._limit = limit
        self._period = period
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.time()
            self._timestamps = [t for t in self._timestamps if now - t < self._period]

            if len(self._timestamps) >= self._limit:
                sleep_time = self._period - (now - self._timestamps[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    # Recurse after sleeping (release and re-acquire lock)
                    return await self._acquire_inner()

            self._timestamps.append(time.time())

    async def _acquire_inner(self) -> None:
        """Re-check after sleeping (called while lock is NOT held)."""
        now = time.time()
        self._timestamps = [t for t in self._timestamps if now - t < self._period]
        if len(self._timestamps) >= self._limit:
            sleep_time = self._period - (now - self._timestamps[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                return await self._acquire_inner()
        self._timestamps.append(time.time())
