"""Memory skills exposed to agents as tools."""
from __future__ import annotations

from typing import Any

from backend.memory.store import get_store
from backend.skills.base import Skill, SkillResult
from backend.skills.registry import registry


class RememberSkill(Skill):
    name = "remember"
    description = "Store a fact in long-term memory."
    parameters = {
        "content": {"type": "string", "required": True},
        "tags": {"type": "array", "items": {"type": "string"}},
    }
    keywords = ("remember", "санах", "store fact")

    async def run(self, content: str, tags: list[str] | None = None, **_: Any) -> SkillResult:
        mid = await get_store().remember(content, tags=tags)
        return SkillResult(ok=True, data={"id": mid, "content": content})


class RecallSkill(Skill):
    name = "recall"
    description = "Search long-term memory by substring."
    parameters = {"query": {"type": "string", "required": True}}
    keywords = ("recall", "санаж", "what did I say about")

    async def run(self, query: str, **_: Any) -> SkillResult:
        rows = await get_store().search_memories(query)
        return SkillResult(ok=True, data={"matches": rows})


class ForgetSkill(Skill):
    name = "forget"
    description = "Delete a memory by id."
    parameters = {"id": {"type": "integer", "required": True}}
    keywords = ("forget",)

    async def run(self, id: int, **_: Any) -> SkillResult:
        ok = await get_store().forget(int(id))
        return SkillResult(ok=ok, data={"id": id, "deleted": ok})


registry.register(RememberSkill())
registry.register(RecallSkill())
registry.register(ForgetSkill())
