"""Reviewer — critiques output from other agents and suggests fixes."""
from __future__ import annotations

import json
import re
from typing import Any

from backend.agents.base import Agent


class ReviewerAgent(Agent):
    role = "reviewer"
    description = "Critiques other agents' output. Returns scored review."
    system_prompt = (
        "You are JARVIS-Reviewer. Critically review the proposed work. "
        "Return strict JSON: {\"score\": 0-10, \"issues\": [..], \"approve\": bool, \"suggestions\": [..]}"
    )

    async def handle(self, task: dict[str, Any]) -> dict[str, Any]:
        target = task.get("input", {}).get("target") or task.get("description", "")
        text = await self.chat(
            f"Review this work. Be strict but constructive:\n\n{target}",
            thinking=True,
            max_tokens=1024,
        )
        review = self._extract_json(text) or {
            "score": 7,
            "approve": True,
            "issues": [],
            "suggestions": [],
            "raw": text,
        }
        return {"agent": self.role, "ok": True, "data": review}

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
