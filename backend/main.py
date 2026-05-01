"""FastAPI entrypoint for Arajim-Jarvis.

Run with:  uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router as rest_router
from backend.api.websocket import ws_router
from backend.config import settings
from backend.core.events import bus
from backend.core.logger import logger
from backend.memory.store import get_store
from backend.upgrade.versioning import init_v1_if_missing


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Booting Arajim-Jarvis backend")
    await get_store().init()
    init_v1_if_missing()
    if settings.nim_auto_discover and settings.nvidia_api_key:
        try:
            from backend.nvidia.client import get_client
            asyncio.create_task(get_client().discover_and_register())
        except Exception as exc:
            logger.warning(f"NIM auto-discovery skipped: {exc}")
    asyncio.create_task(_heartbeat())
    yield
    logger.info("Shutting down")


async def _heartbeat() -> None:
    """Continuous-execution beacon. Never stops while the app is up."""
    while True:
        await bus.publish("heartbeat", {"type": "tick"})
        await asyncio.sleep(15)


app = FastAPI(title="Arajim-Jarvis", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(rest_router, prefix="/api")
app.include_router(ws_router)


@app.get("/")
async def root():
    return {
        "name": "arajim-jarvis",
        "version": "1.0.0",
        "docs": "/docs",
        "ws": "/ws",
    }


def run() -> None:
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
