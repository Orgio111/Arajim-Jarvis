"""Executor — runs concrete steps.

Three-tier fallback:
  1. Caller named a skill -> invoke directly.
  2. Skill auto-select via fast NIM classifier finds a match -> invoke.
  3. Native NIM function calling (tools=) — let the model pick + call any
     registered skill from the OpenAI-compatible tool schema.
  4. Pure NIM answer (no tool).
"""
from __future__ import annotations

import json
from typing import Any

from backend.agents.base import Agent
from backend.core.logger import logger
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
                "agent": self.role, "skill": skill_name,
                "ok": result.ok, "data": result.data, "error": result.error,
            }

        # 2. Auto-pick skill from description
        auto = await registry.auto_select(description or str(inp))
        if auto:
            result = await registry.invoke(auto, **inp)
            return {
                "agent": self.role, "skill": auto,
                "ok": result.ok, "data": result.data, "error": result.error,
            }

        # 3. Native NIM tool calling — let the model pick + invoke a skill
        tool_result = await self._tool_call(description or str(inp))
        if tool_result is not None:
            return tool_result

        # 4. Pure NIM answer (no tool)
        text = await self.chat(description or str(inp))
        return {"agent": self.role, "skill": None, "ok": True,
                "data": {"text": text}}

    async def _tool_call(self, prompt: str) -> dict[str, Any] | None:
        """Use NIM-native function calling. Returns None if no tool was chosen."""
        tools = registry.tool_schemas()
        if not tools:
            return None
        try:
            resp = await self.client.chat(
                model=self.model(needs_tools=True),
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=512, temperature=0.2,
                tools=tools, tool_choice="auto",
            )
        except Exception as exc:
            logger.debug(f"native tool-call failed: {exc}")
            return None

        msg = resp.choices[0].message
        calls = getattr(msg, "tool_calls", None) or []
        if not calls:
            return None

        call = calls[0]
        name = call.function.name
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        result = await registry.invoke(name, **args)
        return {
            "agent": self.role, "skill": name,
            "ok": result.ok, "data": result.data, "error": result.error,
            "via": "nim_tool_call",
        }
