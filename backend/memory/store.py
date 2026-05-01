"""SQLite-backed memory store: persistent facts + chat history.

Two tables:
  - memories: long-term facts the user explicitly stored ("remember this")
  - chats:    rolling conversation history with optional pruning

Triggers:
  - "remember this <X>"  -> insert into memories
  - "forget <id>"        -> delete by id
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import aiosqlite

from backend.config import settings
from backend.core.logger import logger

REMEMBER_RE = re.compile(r"^\s*remember (?:this[:\s]+)?(.+)$", re.IGNORECASE)
FORGET_RE = re.compile(r"^\s*forget\s+(\d+)\s*$", re.IGNORECASE)


SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    content   TEXT NOT NULL,
    tags      TEXT,
    source    TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);

CREATE TABLE IF NOT EXISTS chats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    metadata   TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chats_session ON chats(session_id, created_at);

CREATE TABLE IF NOT EXISTS skills_meta (
    name        TEXT PRIMARY KEY,
    invocations INTEGER DEFAULT 0,
    successes   INTEGER DEFAULT 0,
    failures    INTEGER DEFAULT 0,
    last_used   REAL
);
"""


class MemoryStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = Path(db_path or settings.memory_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def init(self) -> None:
        if self._initialized:
            return
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()
        self._initialized = True
        logger.info(f"Memory store ready: {self.db_path}")

    # ------------------------------------------------------------ persistent
    async def remember(self, content: str, *, tags: list[str] | None = None,
                        source: str = "user") -> int:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO memories (content, tags, source, created_at) VALUES (?, ?, ?, ?)",
                (content, ",".join(tags or []), source, time.time()),
            )
            await db.commit()
            return cur.lastrowid or 0

    async def forget(self, memory_id: int) -> bool:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def list_memories(self, *, limit: int = 100) -> list[dict[str, Any]]:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in rows]

    async def search_memories(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Case-insensitive substring search. Good enough until we add embeddings."""
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM memories WHERE LOWER(content) LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (f"%{query.lower()}%", limit),
            )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ chat
    async def append_chat(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO chats (session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, json.dumps(metadata or {}), time.time()),
            )
            await db.commit()
            await self._prune(db, session_id)
            return cur.lastrowid or 0

    async def get_chat(
        self, session_id: str, *, limit: int | None = None
    ) -> list[dict[str, Any]]:
        await self.init()
        limit = limit or settings.max_chat_history
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM chats WHERE session_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            )
            return list(reversed([dict(r) for r in rows]))

    async def delete_chat(self, session_id: str) -> int:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("DELETE FROM chats WHERE session_id = ?", (session_id,))
            await db.commit()
            return cur.rowcount or 0

    async def list_sessions(self) -> list[dict[str, Any]]:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT session_id, COUNT(*) as turns, "
                "       MAX(created_at) as last_active "
                "FROM chats GROUP BY session_id "
                "ORDER BY last_active DESC"
            )
            return [dict(r) for r in rows]

    async def _prune(self, db: aiosqlite.Connection, session_id: str) -> None:
        await db.execute(
            "DELETE FROM chats WHERE session_id = ? AND id NOT IN ("
            "  SELECT id FROM chats WHERE session_id = ? "
            "  ORDER BY created_at DESC LIMIT ?"
            ")",
            (session_id, session_id, settings.max_chat_history),
        )
        await db.commit()

    # --------------------------------------------------------------- triggers
    @staticmethod
    def parse_remember(text: str) -> str | None:
        m = REMEMBER_RE.match(text or "")
        return m.group(1).strip() if m else None

    @staticmethod
    def parse_forget(text: str) -> int | None:
        m = FORGET_RE.match(text or "")
        return int(m.group(1)) if m else None

    # ---------------------------------------------------------- skill stats
    async def record_skill(self, name: str, success: bool) -> None:
        await self.init()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO skills_meta (name, invocations, successes, failures, last_used) "
                "VALUES (?, 1, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                "  invocations = invocations + 1, "
                "  successes = successes + ?, "
                "  failures = failures + ?, "
                "  last_used = ?",
                (
                    name, int(success), int(not success), time.time(),
                    int(success), int(not success), time.time(),
                ),
            )
            await db.commit()


_singleton: MemoryStore | None = None


def get_store() -> MemoryStore:
    global _singleton
    if _singleton is None:
        _singleton = MemoryStore()
    return _singleton
