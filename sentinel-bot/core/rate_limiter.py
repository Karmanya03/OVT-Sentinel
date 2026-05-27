import asyncio
import time
from collections import defaultdict
from typing import DefaultDict


class TokenBucket:
    def __init__(self, tokens: int, refill_secs: float = 1.0) -> None:
        self.capacity = tokens
        self.tokens = tokens
        self.refill_rate = tokens / refill_secs if refill_secs > 0 else float("inf")
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, cost: int = 1) -> float:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= cost:
                self.tokens -= cost
                wait = 0.0
            else:
                shortfall = cost - self.tokens
                wait = shortfall / self.refill_rate if self.refill_rate > 0 else float("inf")
                self.tokens = 0

            return wait

    async def wait_and_acquire(self, cost: int = 1) -> None:
        wait = await self.acquire(cost)
        if wait > 0:
            await asyncio.sleep(wait)
            await self.acquire(cost)


class RateLimiter:
    def __init__(self, global_rps: float = 10.0) -> None:
        self._buckets: DefaultDict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(tokens=max(1, int(global_rps)), refill_secs=1.0)
        )

    async def acquire(self, key: str = "global", cost: int = 1) -> None:
        await self._buckets[key].wait_and_acquire(cost)
