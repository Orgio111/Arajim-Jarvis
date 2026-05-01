"""Text-to-speech. Default: edge-tts (free, multilingual incl. Mongolian voices)."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from backend.config import settings
from backend.core.logger import logger


# edge-tts voices that work well for Mongolian / English
VOICE_BY_LANG = {
    "mn": "mn-MN-BataaNeural",     # Mongolian male
    "mn-female": "mn-MN-YesuiNeural",  # Mongolian female
    "en": "en-US-GuyNeural",       # JARVIS-esque English male
    "en-female": "en-US-AvaNeural",
}


class TTSProvider:
    async def synth(self, text: str, *, voice: str | None = None) -> bytes:
        raise NotImplementedError


class EdgeTTS(TTSProvider):
    async def synth(self, text: str, *, voice: str | None = None) -> bytes:
        try:
            import edge_tts  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "edge-tts not installed. Run `pip install edge-tts`."
            ) from exc
        v = voice or VOICE_BY_LANG.get(settings.voice_lang) or VOICE_BY_LANG["en"]
        communicate = edge_tts.Communicate(text, v)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)


def get_tts() -> TTSProvider:
    if settings.tts_provider == "edge":
        return EdgeTTS()
    raise ValueError(f"Unknown TTS provider: {settings.tts_provider}")
