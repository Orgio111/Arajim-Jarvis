from backend.skills.registry import SkillRegistry, registry
from backend.skills.base import Skill, SkillResult

# Import built-in skills so they self-register
from backend.skills import (  # noqa: F401
    system_skill, code_skill, web_skill, file_skill, memory_skill, search_skill,
)

__all__ = ["SkillRegistry", "registry", "Skill", "SkillResult"]
