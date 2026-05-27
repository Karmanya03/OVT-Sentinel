import time

import pytest

from core.cache import TTLCache


def test_cache_hit_miss():
    cache = TTLCache(ttl_secs=60, max_size=100)
    assert cache.get("key1") is None
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"


def test_cache_ttl_expiry():
    cache = TTLCache(ttl_secs=1, max_size=100)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"
    time.sleep(1.1)
    assert cache.get("key1") is None


def test_cache_max_size_eviction():
    cache = TTLCache(ttl_secs=60, max_size=3)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.set("c", "3")
    cache.set("d", "4")
    assert cache.get("a") is None
    assert cache.get("b") is not None
    assert cache.get("d") is not None


def test_cache_clear():
    cache = TTLCache(ttl_secs=60, max_size=100)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None
    assert cache.stats["size"] == 0


def test_cache_invalidate():
    cache = TTLCache(ttl_secs=60, max_size=100)
    cache.set("a", "1")
    cache.invalidate("a")
    assert cache.get("a") is None


def test_cache_stats():
    cache = TTLCache(ttl_secs=60, max_size=100)
    assert cache.get("x") is None
    assert cache.get("y") is None
    cache.set("x", "val")
    cache.get("x")
    stats = cache.stats
    assert stats["hits"] == 1
    assert stats["misses"] == 2
    assert stats["size"] == 1
    assert stats["hit_rate"] > 0


def test_make_key_uniqueness():
    cache = TTLCache()
    k1 = cache._make_key("hello", x=1)
    k2 = cache._make_key("hello", x=2)
    k3 = cache._make_key("hello", x=1)
    assert k1 != k2
    assert k1 == k3


def test_ttl_cache_empty_eviction():
    cache = TTLCache(ttl_secs=60, max_size=0)
    cache.set("a", "1")
    assert len(cache._store) == 0


def test_ttl_cache_large_entries():
    cache = TTLCache(ttl_secs=60, max_size=1000)
    for i in range(100):
        cache.set(f"key{i}", f"value{i}")
    assert cache.stats["size"] == 100
    assert cache.get("key0") == "value0"
    assert cache.get("key99") == "value99"
