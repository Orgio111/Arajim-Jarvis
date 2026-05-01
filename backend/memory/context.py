"""Context optimizer.

Two strategies combined:
  1. Auto-summarize: when chat history exceeds `SUMMARIZE_AFTER` turns, the
     oldest block is replaced with a single summary message.
  2. Semantic retrieval: at prompt time, pull the top-K memories + past turns
     most relevant to the current message and inject them as a context block.

Result: prompts stay small even after thousands of turns.
"""
from __future__ import annotations

from typing import Any

from backend.config import settings
from backend.core.logger import logger
from backend.memory.store import get_store
from backend.nvidia.client import get_client
from backend.nvidia.router import router


SUMMARY_PROMPT = (
    "Summarize the following conversation turns into one paragraph (<=120 words). "
    "Capture facts, decisions, and outstanding tasks. Drop pleasantries and meta-talk."
)


async def summarize_old_turns(session_id: str) -> str | None:
    """Replace the oldest half of history with a summary if it exceeds the threshold."""
    store = get_store()
    history = await store.get_chat(session_id, limit=10_000)
    if len(history) <= settings.summarize_after:
        return None

    cutoff = len(history) // 2
    block = history[:cutoff]
    keep = history[cutoff:]

    transcript = "\n".join(f"{h['role']}: {h['content']}" for h in block)
    client = get_client()
    model = router.pick_for("memory")
    resp = await client.chat(
        model=model,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": transcript[:24000]},
        ],
        max_tokens=400,
        temperature=0.2,
    )
    summary = (resp.choices[0].message.content or "").strip()

    # Wipe old block, insert summary, re-insert kept turns
    await store.delete_chat(session_id)
    await store.append_chat(
        session_id, "system", f"[summary of earlier turns]\n{summary}",
        metadata={"kind": "summary"},
    )
    for h in keep:
        await store.append_chat(session_id, h["role"], h["content"],
                                metadata={"resumed": True})
    logger.info(f"Summarized {len(block)} old turns in session {session_id}")
    return summary


async def build_context(session_id: str, query: str, *,
                        k_memories: int = 4, k_turns: int = 4) -> list[dict[str, Any]]:
    """Return a list of message dicts to inject before the user's question."""
    store = get_store()
    out: list[dict[str, Any]] = []

    # Semantic memories
    try:
        mems = await store.semantic_recall(query, k=k_memories, threshold=0.5)
        if mems:
            block = "\n".join(f"- ({m['score']:.2f}) {m['text']}" for m in mems)
            out.append({
                "role": "system",
                "content": f"[relevant memories]\n{block}",
            })
    except Exception as exc:
        logger.debug(f"semantic memory injection skipped: {exc}")

    # Recent chat
    history = await store.get_chat(session_id, limit=settings.summarize_after)
    out.extend({"role": h["role"], "content": h["content"]}
               for h in history[-k_turns * 2:])
    return out
