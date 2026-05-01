"""Filesystem skills."""
from __future__ import annotations

from typing import Any

from backend.skills.base import Skill, SkillResult
from backend.skills.registry import registry
from backend.system.filesystem import fs


class FileReadSkill(Skill):
    name = "file_read"
    description = "Read a file from disk."
    parameters = {"path": {"type": "string", "description": "File path.", "required": True}}
    keywords = ("read file", "open file", "file content")

    async def run(self, path: str, **_: Any) -> SkillResult:
        try:
            content = await fs.read(path)
            return SkillResult(ok=True, data={"path": path, "content": content})
        except Exception as exc:
            return SkillResult(ok=False, error=str(exc))


class FileWriteSkill(Skill):
    name = "file_write"
    description = "Write or append text to a file."
    parameters = {
        "path": {"type": "string", "required": True},
        "content": {"type": "string", "required": True},
        "append": {"type": "boolean"},
    }
    keywords = ("write file", "save file", "create file")

    async def run(self, path: str, content: str, append: bool = False, **_: Any) -> SkillResult:
        try:
            n = await fs.write(path, content, append=append)
            return SkillResult(ok=True, data={"path": path, "bytes": n})
        except Exception as exc:
            return SkillResult(ok=False, error=str(exc))


class FileListSkill(Skill):
    name = "file_list"
    description = "List directory contents."
    parameters = {"path": {"type": "string"}}
    keywords = ("list files", "ls ", "directory")

    async def run(self, path: str = ".", **_: Any) -> SkillResult:
        try:
            return SkillResult(ok=True, data={"entries": await fs.list(path)})
        except Exception as exc:
            return SkillResult(ok=False, error=str(exc))


registry.register(FileReadSkill())
registry.register(FileWriteSkill())
registry.register(FileListSkill())
