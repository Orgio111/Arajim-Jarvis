"""Two-layer cache: exact (hash) → semantic (embedding cosine).

Use case: identical or paraphrased user prompts return the cached reply
instantly. Wrapping the LLM call in `cache.wrap(...)` is the fastest path
to "feels instant" UX.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import numpy as np

from backend.cache.backend import CacheBackend, make_backend
from backend.config import settings
from backend.core.events import bus
from backend.core.logger import logger
from backend.nvidia.embeddings import cosine, get_embedder


@dataclass
class SemanticEntry:
    key: str
    text: str
    vector: list[float]
    value: Any
    expires: float


def _hash_key(namespace: str, text: str) -> str:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    return f"{namespace}:exact:{h}"


class CacheManager:
    def __init__(self) -> None:
        self._backend: CacheBackend = make_backend()
        self._sem_index: dict[str, list[SemanticEntry]] = {}
        self._stats = {"exact_hits": 0, "semantic_hits": 0, "misses": 0, "writes": 0}

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    # ------------------------------------------------------------- exact
    async def get_exact(self, namespace: str, text: str) -> Any | None:
        v = await self._backend.get(_hash_key(namespace, text))
        if v is not None:
            self._stats["exact_hits"] += 1
            await bus.publish("cache", {"type": "hit", "kind": "exact", "ns": namespace})
        return v

    async def set_exact(self, namespace: str, text: str, value: Any,
                         ttl: int | None = None) -> None:
        await self._backend.set(_hash_key(namespace, text), value, ttl or settings.cache_exact_ttl)
        self._stats["writes"] += 1

    # ---------------------------------------------------------- semantic
    async def get_semantic(self, namespace: str, text: str,
                           threshold: float | None = None) -> Any | None:
        thr = threshold if threshold is not None else settings.cache_semantic_threshold
        index = self._sem_index.get(namespace, [])
        if not index:
            self._stats["misses"] += 1
            return None

        vec = (await get_embedder().embed(text))[0]
        now = time.time()
        # Drop expired
        index = [e for e in index if e.expires == 0 or e.expires > now]
        self._sem_index[namespace] = index
        if not index:
            self._stats["misses"] += 1
            return None

        # Argmax cosine
        mat = np.array([e.vector for e in index], dtype=np.float32)
        sims = mat @ vec
        idx = int(np.argmax(sims))
        if float(sims[idx]) >= thr:
            self._stats["semantic_hits"] += 1
            await bus.publish(
                "cache",
                {"type": "hit", "kind": "semantic", "ns": namespace, "score": float(sims[idx])},
            )
            return index[idx].value
        self._stats["misses"] += 1
        return None

    async def set_semantic(self, namespace: str, text: str, value: Any,
                           ttl: int | None = None) -> None:
        ttl = ttl if ttl is not None else settings.cache_semantic_ttl
        vec = (await get_embedder().embed(text))[0].tolist()
        entry = SemanticEntry(
            key=_hash_key(namespace, text),
            text=text,
            vector=vec,
            value=value,
            expires=(time.time() + ttl) if ttl > 0 else 0,
        )
        bucket = self._sem_index.setdefault(namespace, [])
        bucket.append(entry)
        # Bound bucket size
        if len(bucket) > 2000:
            bucket.pop(0)
        self._stats["writes"] += 1

    # ------------------------------------------------------------ wrapper
    async def wrap(
        self,
        *,
        namespace: str,
        key_text: str,
        fn: Callable[[], Awaitable[Any]],
        semantic: bool = True,
        ttl: int | None = None,
    ) -> Any:
        """Single-call helper: exact → semantic → execute → store."""
        hit = await self.get_exact(namespace, key_text)
        if hit is not None:
            return hit
        if semantic:
            hit = await self.get_semantic(namespace, key_text)
            if hit is not None:
                return hit
        value = await fn()
        await self.set_exact(namespace, key_text, value, ttl=ttl)
        if semantic:
            try:
                await self.set_semantic(namespace, key_text, value, ttl=ttl)
            except Exception as exc:
                logger.warning(f"semantic cache write failed: {exc}")
        return value

    async def invalidate(self, namespace: str) -> None:
        """Drop everything for a namespace."""
        self._sem_index.pop(namespace, None)
        for k in await self._backend.keys(f"{namespace}:*"):
            await self._backend.delete(k)


cache = CacheManager()
