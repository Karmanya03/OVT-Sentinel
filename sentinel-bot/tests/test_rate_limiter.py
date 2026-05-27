import pytest
from core.rate_limiter import TokenBucket, RateLimiter


class TestTokenBucket:
    @pytest.mark.asyncio
    async def test_acquire_no_wait(self):
        bucket = TokenBucket(tokens=10, refill_secs=1.0)
        wait = await bucket.acquire(cost=1)
        assert wait == 0.0
        assert bucket.tokens == 9

    @pytest.mark.asyncio
    async def test_acquire_exact_capacity(self):
        bucket = TokenBucket(tokens=3, refill_secs=1.0)
        w1 = await bucket.acquire(cost=3)
        assert w1 == 0.0
        assert bucket.tokens == 0

    @pytest.mark.asyncio
    async def test_acquire_waits_when_empty(self):
        bucket = TokenBucket(tokens=5, refill_secs=1.0)
        await bucket.acquire(cost=5)
        wait = await bucket.acquire(cost=1)
        assert wait > 0

    @pytest.mark.asyncio
    async def test_acquire_refill_over_time(self):
        bucket = TokenBucket(tokens=5, refill_secs=1.0)
        await bucket.acquire(cost=5)
        import asyncio
        await asyncio.sleep(0.1)
        wait = await bucket.acquire(cost=1)
        assert 0 < wait < 1.0

    @pytest.mark.asyncio
    async def test_wait_and_acquire(self):
        bucket = TokenBucket(tokens=2, refill_secs=1.0)
        import asyncio
        await bucket.acquire(cost=2)
        t0 = asyncio.get_event_loop().time()
        await bucket.wait_and_acquire(cost=1)
        elapsed = asyncio.get_event_loop().time() - t0
        assert elapsed >= 0.4

    @pytest.mark.asyncio
    async def test_acquire_zero_division(self):
        bucket = TokenBucket(tokens=5, refill_secs=0)
        wait = await bucket.acquire(cost=1)
        assert wait == 0.0
        assert bucket.tokens == 4

    @pytest.mark.asyncio
    async def test_acquire_cost_larger_than_capacity(self):
        bucket = TokenBucket(tokens=3, refill_secs=1.0)
        wait = await bucket.acquire(cost=10)
        assert wait > 0
        assert bucket.tokens == 0


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_global_default(self):
        rl = RateLimiter(global_rps=10.0)
        await rl.acquire()
        await rl.acquire()
        assert True

    @pytest.mark.asyncio
    async def test_acquire_different_keys(self):
        rl = RateLimiter(global_rps=5.0)
        await rl.acquire("user1")
        await rl.acquire("user2")
        assert True

    @pytest.mark.asyncio
    async def test_acquire_low_rps(self):
        rl = RateLimiter(global_rps=1.0)
        import asyncio
        await rl.acquire("test")
        t0 = asyncio.get_event_loop().time()
        await rl.acquire("test")
        elapsed = asyncio.get_event_loop().time() - t0
        assert elapsed > 0.5
