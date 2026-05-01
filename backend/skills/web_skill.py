"""Lightweight web fetch skill (no scraping ToS violations — plain GET)."""
from __future__ import annotations

from typing import Any

import httpx

from backend.config import settings
from backend.skills.base import Skill, SkillResult
from backend.skills.registry import registry


class WebFetchSkill(Skill):
    name = "web_fetch"
    description = "HTTP GET a URL and return the response text (truncated)."
    parameters = {
        "url": {"type": "string", "description": "Full http(s) URL.", "required": True},
        "max_chars": {"type": "integer", "description": "Truncate body to this many chars."},
    }
    keywords = ("fetch", "url ", "http", "download")

    async def run(self, url: str, max_chars: int = 20_000, **_: Any) -> SkillResult:
        if not settings.allow_network:
            return SkillResult(ok=False, error="Network access disabled.")
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as c:
                r = await c.get(url, headers={"User-Agent": "Arajim-Jarvis/1.0"})
            return SkillResult(
                ok=r.status_code < 400,
                data={
                    "status": r.status_code,
                    "headers": dict(r.headers),
                    "body": r.text[:max_chars],
                    "truncated": len(r.text) > max_chars,
                },
                error=None if r.status_code < 400 else f"HTTP {r.status_code}",
            )
        except Exception as exc:
            return SkillResult(ok=False, error=str(exc))


registry.register(WebFetchSkill())
