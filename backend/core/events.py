"""In-process pub/sub for streaming events to WebSocket clients."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, channel: str = "*") -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers[channel].add(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue) -> None:
        self._subscribers[channel].discard(q)

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        event = {"channel": channel, "ts": time.time(), **payload}
        for sub_channel in (channel, "*"):
            for q in list(self._subscribers.get(sub_channel, [])):
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                await q.put(event)


bus = EventBus()
