"""NVIDIA NIM embeddings.

NIM exposes embedding models on the same OpenAI-compatible endpoint
(`/v1/embeddings`). We wrap the async client so caching, vector memory,
and semantic search all use a single transport.
"""
from __future__ import annotations

import asyncio
from typing import Iterable

import numpy as np

from backend.config import settings
from backend.core.logger import logger
from backend.nvidia.client import get_client


class Embedder:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.nim_embedding_model
        self._sem = asyncio.Semaphore(8)

    async def embed(self, texts: str | Iterable[str]) -> np.ndarray:
        """Return a 2-D numpy array of shape (N, dim)."""
        if isinstance(texts, str):
            inputs = [texts]
        else:
            inputs = list(texts)
        if not inputs:
            return np.zeros((0, settings.vector_dim), dtype=np.float32)

        client = get_client()._client  # underlying AsyncOpenAI for embeddings
        async with self._sem:
            try:
                resp = await client.embeddings.create(
                    model=self.model,
                    input=inputs,
                    extra_body={"input_type": "query", "truncate": "END"},
                )
            except Exception as exc:
                logger.warning(f"NIM embeddings failed ({self.model}): {exc}")
                # Fallback: hash-based pseudo-embedding so the system keeps working
                return _hash_embeddings(inputs, dim=settings.vector_dim)

        vectors = np.array([d.embedding for d in resp.data], dtype=np.float32)
        # Normalize for cosine similarity reuse
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms


def _hash_embeddings(texts: list[str], dim: int) -> np.ndarray:
    """Deterministic fallback when the embeddings endpoint is unavailable."""
    rng = np.random.default_rng(0)
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        seed = abs(hash(t)) % (2**32 - 1)
        out[i] = rng.standard_normal(dim) * 0  # placeholder
        r = np.random.default_rng(seed)
        v = r.standard_normal(dim).astype(np.float32)
        v /= max(np.linalg.norm(v), 1e-9)
        out[i] = v
    return out


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D vectors. Assumes normalized inputs."""
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


_singleton: Embedder | None = None


def get_embedder() -> Embedder:
    global _singleton
    if _singleton is None:
        _singleton = Embedder()
    return _singleton
