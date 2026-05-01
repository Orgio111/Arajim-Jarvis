"""Loguru-based logger with file + console sinks."""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from backend.config import settings


def setup_logger() -> None:
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - {message}",
    )
    logger.add(
        log_dir / "jarvis.log",
        level="DEBUG",
        rotation="20 MB",
        retention="30 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
    )


setup_logger()

__all__ = ["logger"]
