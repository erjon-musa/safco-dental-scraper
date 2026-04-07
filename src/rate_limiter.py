import asyncio
import time


class RateLimiter:
    def __init__(self, delay_seconds: float = 2.0, max_concurrent: int = 3):
        self._delay = delay_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait for rate limit and acquire semaphore."""
        await self._semaphore.acquire()
        async with self._lock:
            now = time.monotonic()
            wait_time = self._delay - (now - self._last_request_time)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_request_time = time.monotonic()

    def release(self):
        self._semaphore.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        self.release()
