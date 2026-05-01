"""Planner — decomposes user intent into a structured plan of steps."""
from __future__ import annotations

import json
import re
from typing import Any

from backend.agents.base import Agent
from backend.core.logger import logger
from backend.skills.registry import registry


PLANNER_SYSTEM = (
    "You are JARVIS-Planner. You decompose the user's request into a JSON plan "
    "of executable steps. You DO NOT execute anything yourself.\n\n"
    "Respond with strict JSON of the form:\n"
    "{\n"
    '  "intent": "<one-line summary>",\n'
    '  "steps": [\n'
    '    {"id": 1, "agent": "executor|coder|reviewer|optimizer", "skill": "<skill_name or null>", '
    '"description": "...", "input": {...}, "depends_on": []},\n'
    "    ...\n"
    "  ],\n"
    '  "needs_confirmation": false\n'
    "}\n\n"
    "Available skills: {skills}\n"
    "Be concise. Aim for 1-6 steps. If the request is trivial, emit one step."
)


class PlannerAgent(Agent):
    role = "planner"
    description = "Reasoning model that decomposes goals into structured plans."

    @property
    def system_prompt(self) -> str:  # type: ignore[override]
        skill_names = ", ".join(registry.all.keys()) or "(none)"
        return PLANNER_SYSTEM.format(skills=skill_names)

    async def handle(self, task: dict[str, Any]) -> dict[str, Any]:
        goal = task.get("goal") or task.get("user_message", "")
        raw = await self.chat(
            f"User goal: {goal}\nProduce the JSON plan now.",
            thinking=True,
            max_tokens=2048,
        )
        plan = self._extract_json(raw)
        if not plan or "steps" not in plan:
            logger.warning(f"Planner produced unparseable output, wrapping: {raw[:200]}")
            plan = {
                "intent": goal,
                "steps": [
                    {
                        "id": 1,
                        "agent": "executor",
                        "skill": None,
                        "description": goal,
                        "input": {"user_message": goal},
                        "depends_on": [],
                    }
                ],
                "needs_confirmation": False,
            }
        return plan

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        # Try fenced block first
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        candidates = []
        if fence:
            candidates.append(fence.group(1))
        # Greedy braces fallback
        brace = re.search(r"(\{.*\})", text, re.DOTALL)
        if brace:
            candidates.append(brace.group(1))
        for c in candidates:
            try:
                return json.loads(c)
            except json.JSONDecodeError:
                continue
        return None
