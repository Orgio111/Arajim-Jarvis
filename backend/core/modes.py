"""Execution modes: Full Auto / Smart Assist / Manual."""
from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    FULL_AUTO = "full_auto"
    SMART_ASSIST = "smart_assist"
    MANUAL = "manual"


class ModeController:
    def __init__(self, mode: Mode = Mode.SMART_ASSIST) -> None:
        self._mode = mode

    @property
    def mode(self) -> Mode:
        return self._mode

    def set(self, mode: Mode | str) -> Mode:
        self._mode = Mode(mode) if isinstance(mode, str) else mode
        return self._mode

    def needs_confirmation(self, *, dangerous: bool) -> bool:
        if self._mode == Mode.MANUAL:
            return True
        if self._mode == Mode.FULL_AUTO:
            return False
        return dangerous  # SMART_ASSIST


controller = ModeController()
