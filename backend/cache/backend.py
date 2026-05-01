"""Cache backends: in-process LRU+TTL or Redis. Same async interface."""
from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from typing import Any, Iterable

from backend.config import settings
from backend.core.logger import logger


class CacheBackend:
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def keys(self, pattern: str = "*") -> list[str]: ...
    async def clear(self) -> None: ...


class MemoryBackend(CacheBackend):
    def __init__(self, max_entries: int = 5000) -> None:
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = asyncio.Lock()
        self._max = max_entries

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expires, value = item
            if expires and expires < time.time():
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        async with self._lock:
            self._data[key] = (time.time() + ttl if ttl > 0 else 0, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def keys(self, pattern: str = "*") -> list[str]:
        async with self._lock:
            if pattern == "*":
                return list(self._data.keys())
            return [k for k in self._data if pattern.replace("*", "") in k]

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()


class RedisBackend(CacheBackend):
    def __init__(self, url: str) -> None:
        try:
            import redis.asyncio as redis  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "redis not installed; pip install redis[hiredis] or use CACHE_BACKEND=memory"
            ) from exc
        self._r = redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        raw = await self._r.get(key)
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if ttl > 0:
            await self._r.setex(key, ttl, json.dumps(value, default=str))
        else:
            await self._r.set(key, json.dumps(value, default=str))

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def keys(self, pattern: str = "*") -> list[str]:
        return [k async for k in self._r.scan_iter(match=pattern)]

    async def clear(self) -> None:
        async for k in self._r.scan_iter("*"):
            await self._r.delete(k)


def make_backend() -> CacheBackend:
    if settings.cache_backend == "redis":
        try:
            return RedisBackend(settings.redis_url)
        except Exception as exc:
            logger.warning(f"Redis unavailable, falling back to memory: {exc}")
    return MemoryBackend()
