"""Skill registry + auto-selection.

Two selection paths:
  1. Direct: caller names the skill.
  2. Auto: a fast NIM model classifies the user request and picks the best skill.
"""
from __future__ import annotations

import json
from typing import Any

from backend.core.logger import logger
from backend.memory.store import get_store
from backend.nvidia.client import get_client
from backend.nvidia.router import router
from backend.skills.base import Skill, SkillResult


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if not skill.name:
            raise ValueError("Skill must have a name")
        self._skills[skill.name] = skill
        logger.debug(f"Registered skill: {skill.name}")

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    @property
    def all(self) -> dict[str, Skill]:
        return dict(self._skills)

    def descriptions(self) -> list[dict[str, str]]:
        return [
            {"name": s.name, "description": s.description, "keywords": list(s.keywords)}
            for s in self._skills.values()
        ]

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [s.to_tool_schema() for s in self._skills.values()]

    # ---------------------------------------------------------- auto-select
    async def auto_select(self, user_request: str) -> str | None:
        """Ask a fast NIM model which skill (if any) best matches."""
        if not self._skills:
            return None

        # Cheap keyword pre-filter
        kw_hits = [
            s.name
            for s in self._skills.values()
            if any(k in user_request.lower() for k in s.keywords)
        ]
        if len(kw_hits) == 1:
            return kw_hits[0]

        prompt = (
            "You are a skill router. Given the user's request and a list of skills, "
            "respond with ONLY the skill name to use, or 'none' if no skill fits.\n\n"
            f"User: {user_request}\n\nSkills:\n"
            + "\n".join(f"- {s.name}: {s.description}" for s in self._skills.values())
            + "\n\nAnswer with one skill name or 'none'."
        )
        client = get_client()
        try:
            resp = await client.chat(
                model=router.pick_for("router", prefer_speed=True),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=32,
                temperature=0.0,
            )
            ans = (resp.choices[0].message.content or "").strip().split()[0].lower()
            return ans if ans in self._skills else None
        except Exception as exc:
            logger.warning(f"auto_select failed: {exc}")
            return kw_hits[0] if kw_hits else None

    # ----------------------------------------------------------------- run
    async def invoke(self, name: str, **kwargs: Any) -> SkillResult:
        skill = self.get(name)
        if not skill:
            return SkillResult(ok=False, error=f"unknown skill: {name}")
        try:
            result = await skill.run(**kwargs)
        except Exception as exc:
            logger.exception(f"Skill {name} failed")
            result = SkillResult(ok=False, error=str(exc))
        await get_store().record_skill(name, result.ok)
        return result


registry = SkillRegistry()
