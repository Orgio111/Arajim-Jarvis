"""Executor — runs concrete steps, invoking skills."""
from __future__ import annotations

from typing import Any

from backend.agents.base import Agent
from backend.skills.registry import registry


class ExecutorAgent(Agent):
    role = "executor"
    description = "Runs steps. Invokes skills, talks to the OS, returns results."
    system_prompt = (
        "You are JARVIS-Executor. You carry out one step at a time. "
        "If a skill is provided, call it via tool-use. Otherwise produce the answer directly. "
        "Be terse and accurate."
    )

    async def handle(self, task: dict[str, Any]) -> dict[str, Any]:
        skill_name = task.get("skill")
        inp = task.get("input", {}) or {}
        description = task.get("description", "")

        # 1. Direct skill name
        if skill_name:
            result = await registry.invoke(skill_name, **inp)
            return {
                "agent": self.role,
                "skill": skill_name,
                "ok": result.ok,
                "data": result.data,
                "error": result.error,
            }

        # 2. Auto-pick skill from description
        auto = await registry.auto_select(description or str(inp))
        if auto:
            result = await registry.invoke(auto, **inp)
            return {
                "agent": self.role,
                "skill": auto,
                "ok": result.ok,
                "data": result.data,
                "error": result.error,
            }

        # 3. Pure NIM answer (no tool)
        text = await self.chat(description or str(inp))
        return {"agent": self.role, "skill": None, "ok": True, "data": {"text": text}}
