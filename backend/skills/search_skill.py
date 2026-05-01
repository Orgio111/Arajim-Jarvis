"""Web search and deep search skills."""
from __future__ import annotations

from typing import Any

from backend.search.deep import deep_search
from backend.search.web import web_search
from backend.skills.base import Skill, SkillResult
from backend.skills.registry import registry


class WebSearchSkill(Skill):
    name = "web_search"
    description = "Real-time web search. Returns titles + URLs + snippets."
    parameters = {
        "query": {"type": "string", "required": True},
        "k": {"type": "integer", "description": "Number of results (default 6)."},
    }
    keywords = ("search", "хайх", "google", "look up", "find online")

    async def run(self, query: str, k: int = 6, **_: Any) -> SkillResult:
        results = await web_search(query, k=k)
        return SkillResult(
            ok=bool(results),
            data={"results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source}
                for r in results
            ]},
        )


class DeepSearchSkill(Skill):
    name = "deep_search"
    description = (
        "Multi-step research with cross-source verification. Slower but high confidence. "
        "Use for complex research questions."
    )
    parameters = {
        "question": {"type": "string", "required": True},
        "max_steps": {"type": "integer"},
    }
    keywords = ("deep research", "research", "investigate", "судлах", "verify")

    async def run(self, question: str, max_steps: int | None = None, **_: Any) -> SkillResult:
        r = await deep_search(question, max_steps=max_steps)
        return SkillResult(
            ok=bool(r.answer),
            data={
                "answer": r.answer,
                "citations": r.citations,
                "steps": r.steps,
                "elapsed_s": r.elapsed_s,
            },
        )


registry.register(WebSearchSkill())
registry.register(DeepSearchSkill())
