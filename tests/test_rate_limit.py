# ABOUTME: Unit tests for the async-safe timestamp-based RateLimiter.
# ABOUTME: Tests acquire behavior, blocking, window expiry, and concurrent access.

import asyncio
import time

import pytest

from link_content_scraper.rate_limit import RateLimiter


class TestAcquire:
    async def test_acquires_up_to_limit_without_blocking(self):
        limiter = RateLimiter(limit=3, period=10)
        start = time.time()
        for _ in range(3):
            await limiter.acquire()
        elapsed = time.time() - start
        assert elapsed < 0.5

    async def test_blocks_after_limit_exhausted(self):
        limiter = RateLimiter(limit=2, period=1)
        await limiter.acquire()
        await limiter.acquire()
        start = time.time()
        await limiter.acquire()
        elapsed = time.time() - start
        assert elapsed >= 0.8  # Should wait ~1 second for window to expire


class TestWindowExpiry:
    async def test_can_acquire_after_window_expires(self):
        limiter = RateLimiter(limit=1, period=1)
        await limiter.acquire()
        await asyncio.sleep(1.1)
        start = time.time()
        await limiter.acquire()
        elapsed = time.time() - start
        assert elapsed < 0.5


class TestConcurrency:
    async def test_concurrent_acquires_respect_limit(self):
        limiter = RateLimiter(limit=3, period=2)

        timestamps: list[float] = []

        async def acquire_and_record():
            await limiter.acquire()
            timestamps.append(time.time())

        start = time.time()
        await asyncio.gather(*[acquire_and_record() for _ in range(6)])
        elapsed = time.time() - start

        # First 3 should be near-instant, next 3 after ~2s window
        assert elapsed >= 1.5
        # All 6 should complete
        assert len(timestamps) == 6
