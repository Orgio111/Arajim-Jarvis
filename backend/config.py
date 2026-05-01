"""Centralized settings loaded from .env."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # NVIDIA NIM
    nvidia_api_key: str = Field(default="", alias="NVIDIA_API_KEY")
    nvidia_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1", alias="NVIDIA_BASE_URL"
    )

    # Model tiers — the router picks dynamically; these are defaults.
    nim_model_reasoning: str = Field(
        default="nvidia/llama-3.3-nemotron-ultra-253b", alias="NIM_MODEL_REASONING"
    )
    nim_model_general: str = Field(
        default="nvidia/llama-3.3-nemotron-super-49b", alias="NIM_MODEL_GENERAL"
    )
    nim_model_code: str = Field(
        default="deepseek-ai/deepseek-v4-flash", alias="NIM_MODEL_CODE"
    )
    nim_model_fast: str = Field(
        default="nvidia/llama-3.3-nemotron-nano-8b", alias="NIM_MODEL_FAST"
    )
    nim_model_long_context: str = Field(
        default="moonshotai/kimi-k2.5", alias="NIM_MODEL_LONG_CONTEXT"
    )

    # Server
    backend_host: str = Field(default="0.0.0.0", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    frontend_port: int = Field(default=5173, alias="FRONTEND_PORT")

    # Execution
    default_mode: Literal["full_auto", "smart_assist", "manual"] = Field(
        default="smart_assist", alias="DEFAULT_MODE"
    )
    allow_terminal: bool = Field(default=True, alias="ALLOW_TERMINAL")
    allow_filesystem: bool = Field(default=True, alias="ALLOW_FILESYSTEM")
    allow_network: bool = Field(default=True, alias="ALLOW_NETWORK")
    sandbox_dangerous: bool = Field(default=True, alias="SANDBOX_DANGEROUS")
    require_confirm_for: str = Field(
        default="rm,sudo,format,dd,mkfs,shutdown,reboot", alias="REQUIRE_CONFIRM_FOR"
    )

    # Memory
    memory_db_path: str = Field(default="./data/memory.db", alias="MEMORY_DB_PATH")
    max_chat_history: int = Field(default=200, alias="MAX_CHAT_HISTORY")

    # Voice
    voice_enabled: bool = Field(default=True, alias="VOICE_ENABLED")
    voice_lang: str = Field(default="mn", alias="VOICE_LANG")
    stt_provider: str = Field(default="whisper", alias="STT_PROVIDER")
    tts_provider: str = Field(default="edge", alias="TTS_PROVIDER")

    # Upgrade
    upgrade_dir: str = Field(default="./versions", alias="UPGRADE_DIR")
    current_version: int = Field(default=1, alias="CURRENT_VERSION")
    upgrade_confirm_phrase: str = Field(
        default="upgrade myself", alias="UPGRADE_CONFIRM_PHRASE"
    )

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_dir: str = Field(default="./logs", alias="LOG_DIR")

    @property
    def confirm_keywords(self) -> list[str]:
        return [k.strip() for k in self.require_confirm_for.split(",") if k.strip()]

    @property
    def root(self) -> Path:
        return ROOT


settings = Settings()
