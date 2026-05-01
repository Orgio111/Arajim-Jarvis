"""Skill base class. A Skill is a named, callable capability with a JSON schema."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillResult:
    ok: bool
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class Skill(ABC):
    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}
    keywords: tuple[str, ...] = ()  # for keyword-based matching

    @abstractmethod
    async def run(self, **kwargs: Any) -> SkillResult:
        ...

    def to_tool_schema(self) -> dict[str, Any]:
        """OpenAI tool-call schema for NIM models."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": [
                        k for k, v in self.parameters.items()
                        if isinstance(v, dict) and v.get("required")
                    ],
                },
            },
        }
