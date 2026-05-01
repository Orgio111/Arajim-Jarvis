"""Coder — writes / refactors code using the Code-tier NIM model."""
from __future__ import annotations

import re
from typing import Any

from backend.agents.base import Agent


class CoderAgent(Agent):
    role = "coder"
    description = "Writes, refactors, and reviews code via DeepSeek-V4 / Qwen-Coder NIM models."
    system_prompt = (
        "You are JARVIS-Coder. Write production-quality code. "
        "Prefer clarity over cleverness. Always return code in fenced blocks."
    )

    async def handle(self, task: dict[str, Any]) -> dict[str, Any]:
        instruction = task.get("description") or task.get("input", {}).get("instruction", "")
        language = task.get("input", {}).get("language", "python")
        context = task.get("input", {}).get("context", "")

        prompt = (
            f"Language: {language}\n"
            f"Task: {instruction}\n"
            + (f"\nExisting code:\n```{language}\n{context}\n```" if context else "")
        )
        text = await self.chat(prompt, max_tokens=4096)
        return {
            "agent": self.role,
            "ok": True,
            "data": {"output": text, "code": self._extract_code(text)},
        }

    @staticmethod
    def _extract_code(text: str) -> str | None:
        m = re.search(r"```[a-zA-Z]*\n(.*?)```", text, re.DOTALL)
        return m.group(1).strip() if m else None
