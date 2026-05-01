"""WebSocket bridge: streams everything on the event bus to the UI."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.events import bus
from backend.core.logger import logger

ws_router = APIRouter()


@ws_router.websocket("/ws")
async def stream(ws: WebSocket) -> None:
    await ws.accept()
    queue = bus.subscribe("*")
    logger.info("WS client connected")

    async def reader() -> None:
        try:
            async for msg in ws.iter_text():
                # Allow client to publish too (e.g., chat) — kept for future use.
                try:
                    payload = json.loads(msg)
                    await bus.publish(payload.get("channel", "client"), payload)
                except json.JSONDecodeError:
                    pass
        except WebSocketDisconnect:
            return

    async def writer() -> None:
        try:
            while True:
                event = await queue.get()
                await ws.send_text(json.dumps(event, default=str))
        except WebSocketDisconnect:
            return

    try:
        await asyncio.gather(reader(), writer())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe("*", queue)
        logger.info("WS client disconnected")
