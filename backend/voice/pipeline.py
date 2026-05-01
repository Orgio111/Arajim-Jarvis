"""End-to-end voice pipeline: audio bytes -> text -> orchestrator -> TTS."""
from __future__ import annotations

from typing import Any

from backend.agents.orchestrator import orchestrator
from backend.config import settings
from backend.core.events import bus
from backend.core.logger import logger
from backend.voice.stt import get_stt
from backend.voice.tts import get_tts


class VoicePipeline:
    def __init__(self) -> None:
        self._stt = None
        self._tts = None
        self._enabled = settings.voice_enabled
        self._active = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def active(self) -> bool:
        return self._active

    def toggle(self, on: bool | None = None) -> bool:
        self._active = (not self._active) if on is None else bool(on)
        return self._active

    def _ensure(self) -> None:
        if self._stt is None:
            self._stt = get_stt()
        if self._tts is None:
            self._tts = get_tts()

    async def transcribe(self, audio: bytes, *, language: str | None = None) -> str:
        self._ensure()
        text = await self._stt.transcribe(audio, language=language or settings.voice_lang)
        await bus.publish("voice", {"type": "stt", "text": text})
        return text

    async def synth(self, text: str, *, voice: str | None = None) -> bytes:
        self._ensure()
        audio = await self._tts.synth(text, voice=voice)
        await bus.publish("voice", {"type": "tts", "bytes": len(audio)})
        return audio

    async def handle_audio(self, audio: bytes, *, session_id: str = "voice") -> dict[str, Any]:
        """Full loop: transcribe -> orchestrator -> synth response audio."""
        self._ensure()
        text = await self.transcribe(audio)
        if not text:
            return {"text": "", "reply": "", "audio": b""}
        outcome = await orchestrator.handle(session_id=session_id, user_message=text)
        audio_out = await self.synth(outcome["reply"])
        return {"text": text, "reply": outcome["reply"], "audio": audio_out, "plan": outcome.get("plan")}


voice = VoicePipeline()
