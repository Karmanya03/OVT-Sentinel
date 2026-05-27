import hashlib
import heapq
import json
import time
from typing import Any, Callable, Optional

from config import Settings


class TTLCache:
    def __init__(self, ttl_secs: int = 300, max_size: int = 1000):
        self._ttl_secs = ttl_secs
        self._max_size = max_size
        self._store: dict[str, tuple[float, str]] = {}
        self._heap: list[tuple[float, str]] = []
        self._hits = 0
        self._misses = 0

    def _make_key(self, *args, **kwargs) -> str:
        raw = json.dumps((args, sorted(kwargs.items())), sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> Optional[str]:
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        ts, value = entry
        if time.monotonic() - ts > self._ttl_secs:
            del self._store[key]
            self._misses += 1
            return None
        self._hits += 1
        # update access time for LRU ordering
        now = time.monotonic()
        self._store[key] = (now, value)
        heapq.heappush(self._heap, (now, key))
        return value

    def set(self, key: str, value: str) -> None:
        if self._max_size == 0:
            return
        if len(self._store) >= self._max_size:
            self._evict_lru()
        now = time.monotonic()
        self._store[key] = (now, value)
        heapq.heappush(self._heap, (now, key))

    def _evict_lru(self) -> None:
        while self._heap:
            ts, key = heapq.heappop(self._heap)
            entry = self._store.get(key)
            if entry is None:
                continue
            store_ts, _ = entry
            if ts != store_ts:
                continue
            del self._store[key]
            return

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
        self._heap.clear()
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
            "max_size": self._max_size,
            "ttl_secs": self._ttl_secs,
        }


_llm_cache: Optional[TTLCache] = None


def get_llm_cache(config: Settings) -> TTLCache:
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = TTLCache(ttl_secs=config.llm_cache_ttl_secs, max_size=config.llm_cache_max_size)
    return _llm_cache


class cached:
    def __init__(self, ttl_secs: Optional[int] = None):
        self._ttl_override = ttl_secs

    def __call__(self, func: Callable):
        import functools

        @functools.wraps(func)
        async def wrapper(llm_brain, *args, **kwargs):
            config = getattr(llm_brain, "config", None)
            if not config or not config.use_llm_cache:
                return await func(llm_brain, *args, **kwargs)

            cache = get_llm_cache(config)
            ttl = self._ttl_override if self._ttl_override is not None else config.llm_cache_ttl_secs

            key_parts = [func.__name__, str(args), str(sorted(kwargs.items()))]
            if hasattr(llm_brain.config, "llm_provider"):
                key_parts.append(llm_brain.config.llm_provider)
            if hasattr(llm_brain.config, llm_brain.config.llm_provider + "_model"):
                key_parts.append(getattr(llm_brain.config, llm_brain.config.llm_provider + "_model", ""))

            import hashlib, json
            raw = json.dumps(key_parts, sort_keys=True, default=str)
            cache_key = hashlib.sha256(raw.encode()).hexdigest()

            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            result = await func(llm_brain, *args, **kwargs)
            cache.set(cache_key, result)
            return result

        return wrapper
