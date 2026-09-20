"""Rate limiter implementing token bucket / sliding window and concurrency control."""
import asyncio
import time
from utils.logger import logger


class AsyncRateLimiter:
    """Sliding-window rate limiter for asynchronous operations like AI API calls."""

    def __init__(self, max_calls_per_minute: int = 6):
        self.max_calls = max_calls_per_minute
        self.period = 60.0  # seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until capacity is available under the rate limit."""
        while True:
            async with self._lock:
                now = time.monotonic()
                # Prune timestamps older than period
                self._timestamps = [t for t in self._timestamps if now - t < self.period]
                
                if len(self._timestamps) < self.max_calls:
                    self._timestamps.append(now)
                    return
                
                # Compute wait time until oldest timestamp expires
                sleep_needed = self.period - (now - self._timestamps[0]) + 0.05
            
            logger.debug(f"Rate limit reached ({self.max_calls}/min). Backing off for {sleep_needed:.2f}s")
            await asyncio.sleep(sleep_needed)


class ConcurrencyLimiter:
    """Semaphore-based limiter for capping parallel conversation executions."""

    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def __aenter__(self):
        await self._semaphore.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._semaphore.release()
