"""Speech-to-text. Default provider: faster-whisper (multilingual incl. Mongolian)."""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

from backend.config import settings
from backend.core.logger import logger


class STTProvider:
    async def transcribe(self, audio_bytes: bytes, *, language: str | None = None) -> str:
        raise NotImplementedError


class WhisperSTT(STTProvider):
    """Wraps faster-whisper. Loaded lazily so import is cheap."""

    def __init__(self, model_size: str = "small") -> None:
        self.model_size = model_size
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "faster-whisper not installed. Run `pip install faster-whisper`."
            ) from exc
        # int8 keeps it CPU-friendly; switch to "float16" + device="cuda" if you have a GPU.
        self._model = WhisperModel(self.model_size, device="auto", compute_type="int8")
        logger.info(f"Loaded Whisper {self.model_size}")

    async def transcribe(self, audio_bytes: bytes, *, language: str | None = None) -> str:
        return await asyncio.to_thread(self._sync_transcribe, audio_bytes, language)

    def _sync_transcribe(self, audio_bytes: bytes, language: str | None) -> str:
        self._load()
        # Whisper accepts a path or numpy array; easiest path is a temp file via BytesIO.
        # faster-whisper handles BinaryIO in newer versions.
        audio = io.BytesIO(audio_bytes)
        segments, _ = self._model.transcribe(
            audio,
            language=language or settings.voice_lang,
            beam_size=5,
            vad_filter=True,
        )
        return "".join(s.text for s in segments).strip()


def get_stt() -> STTProvider:
    if settings.stt_provider == "whisper":
        return WhisperSTT()
    raise ValueError(f"Unknown STT provider: {settings.stt_provider}")
