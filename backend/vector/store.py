"""Vector store with two backends.

`numpy`: pure-numpy dense matrix, persisted as .npz. Good up to ~50k entries.
`faiss`: faiss-cpu IndexFlatIP for fast cosine search. Optional dependency.

Both are pluggable behind the same async interface.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from backend.config import settings
from backend.core.logger import logger
from backend.nvidia.embeddings import get_embedder


@dataclass
class VectorRecord:
    id: int
    text: str
    metadata: dict[str, Any]
    created_at: float


class VectorStore:
    def __init__(self) -> None:
        self.dim = settings.vector_dim
        self.path = Path(settings.vector_db_path)
        self._lock = asyncio.Lock()
        self._matrix: np.ndarray = np.zeros((0, self.dim), dtype=np.float32)
        self._records: list[VectorRecord] = []
        self._faiss = None
        if settings.vector_backend == "faiss":
            self._init_faiss()
        self._load()

    # ------------------------------------------------------------- backends
    def _init_faiss(self) -> None:
        try:
            import faiss  # type: ignore
            self._faiss = faiss.IndexFlatIP(self.dim)
        except Exception as exc:
            logger.warning(f"faiss unavailable, falling back to numpy: {exc}")
            self._faiss = None

    # ----------------------------------------------------------- persistence
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = np.load(self.path, allow_pickle=True)
            self._matrix = data["matrix"].astype(np.float32)
            recs = json.loads(str(data["records"]))
            self._records = [VectorRecord(**r) for r in recs]
            if self._faiss is not None and self._matrix.size:
                self._faiss.add(self._matrix)
            logger.info(f"Vector store loaded: {len(self._records)} records")
        except Exception as exc:
            logger.warning(f"Failed loading vector store: {exc}")

    async def save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                self.path,
                matrix=self._matrix,
                records=json.dumps(
                    [r.__dict__ for r in self._records], default=str
                ),
            )

    # ----------------------------------------------------------------- ops
    async def add(self, text: str, metadata: dict[str, Any] | None = None) -> int:
        vec = (await get_embedder().embed(text))[0].astype(np.float32)
        async with self._lock:
            rid = len(self._records)
            self._records.append(VectorRecord(
                id=rid, text=text, metadata=metadata or {}, created_at=time.time(),
            ))
            self._matrix = np.vstack([self._matrix, vec[None, :]]) if self._matrix.size \
                else vec[None, :]
            if self._faiss is not None:
                self._faiss.add(vec[None, :])
        await self.save()
        return rid

    async def search(self, query: str, k: int = 5,
                     threshold: float = 0.0) -> list[dict[str, Any]]:
        if not self._records:
            return []
        qvec = (await get_embedder().embed(query))[0].astype(np.float32)

        if self._faiss is not None:
            sims, idxs = self._faiss.search(qvec[None, :], min(k, len(self._records)))
            hits = list(zip(idxs[0].tolist(), sims[0].tolist()))
        else:
            sims = self._matrix @ qvec
            top_k = np.argsort(-sims)[: min(k, len(self._records))]
            hits = [(int(i), float(sims[i])) for i in top_k]

        return [
            {
                "id": self._records[i].id,
                "text": self._records[i].text,
                "metadata": self._records[i].metadata,
                "score": float(s),
                "created_at": self._records[i].created_at,
            }
            for i, s in hits if float(s) >= threshold
        ]

    async def find_related(self, record_id: int, k: int = 4,
                           threshold: float = 0.6) -> list[dict[str, Any]]:
        if record_id < 0 or record_id >= len(self._records):
            return []
        qvec = self._matrix[record_id]
        sims = self._matrix @ qvec
        order = np.argsort(-sims)
        out = []
        for i in order:
            i = int(i)
            if i == record_id:
                continue
            score = float(sims[i])
            if score < threshold:
                break
            out.append({
                "id": self._records[i].id,
                "text": self._records[i].text,
                "score": score,
            })
            if len(out) >= k:
                break
        return out

    @property
    def size(self) -> int:
        return len(self._records)


_singleton: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _singleton
    if _singleton is None:
        _singleton = VectorStore()
    return _singleton
