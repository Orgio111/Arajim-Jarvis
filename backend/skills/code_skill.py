"""Code-generation skill — uses the Coder-tier NIM model."""
from __future__ import annotations

from typing import Any

from backend.nvidia.client import get_client
from backend.nvidia.router import router
from backend.skills.base import Skill, SkillResult
from backend.skills.registry import registry


class CodeGenSkill(Skill):
    name = "code_gen"
    description = "Generate, refactor, or review code. Routes to the best NIM coder model."
    parameters = {
        "instruction": {"type": "string", "description": "What to do.", "required": True},
        "language": {"type": "string", "description": "Target language."},
        "context": {"type": "string", "description": "Existing code to operate on."},
    }
    keywords = ("code", "function", "refactor", "implement", "fix bug", "класс", "функц")

    async def run(self, instruction: str, language: str = "python",
                  context: str = "", **_: Any) -> SkillResult:
        msg = (
            f"You are an expert {language} engineer. Produce production-quality code.\n\n"
            f"Task: {instruction}\n\n"
            + (f"Existing code:\n```{language}\n{context}\n```\n" if context else "")
            + "Return only the code, no explanation, in a single fenced block."
        )
        client = get_client()
        model = router.pick_for("coder", prefer_quality=True)
        resp = await client.chat(
            model=model,
            messages=[{"role": "user", "content": msg}],
            max_tokens=4096,
            temperature=0.2,
        )
        return SkillResult(
            ok=True,
            data={"code": resp.choices[0].message.content, "model": model},
        )


registry.register(CodeGenSkill())
