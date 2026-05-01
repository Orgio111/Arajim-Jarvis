"""System-level skills: terminal exec, process info."""
from __future__ import annotations

from typing import Any

import psutil

from backend.skills.base import Skill, SkillResult
from backend.skills.registry import registry
from backend.system.terminal import terminal


class TerminalExecSkill(Skill):
    name = "terminal_exec"
    description = "Execute a shell command on the host machine. Streams output to the UI."
    parameters = {
        "command": {"type": "string", "description": "The shell command to run.", "required": True},
        "cwd": {"type": "string", "description": "Working directory (optional)."},
        "admin": {"type": "boolean", "description": "Run with sudo / elevated privileges."},
    }
    keywords = ("run ", "execute", "shell", "command", "terminal", "$ ")

    async def run(self, command: str, cwd: str | None = None, admin: bool = False, **_: Any) -> SkillResult:
        result = await terminal.run(command, cwd=cwd, admin=admin)
        return SkillResult(
            ok=result.returncode == 0,
            data={
                "command": result.command,
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-2000:],
                "duration_s": result.duration_s,
            },
            error=None if result.returncode == 0 else f"exit {result.returncode}",
        )


class SystemInfoSkill(Skill):
    name = "system_info"
    description = "Return CPU, memory, disk, and network usage of the host."
    parameters = {}
    keywords = ("system info", "cpu", "memory", "ram", "disk usage")

    async def run(self, **_: Any) -> SkillResult:
        vm = psutil.virtual_memory()
        info = {
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "cpu_count": psutil.cpu_count(),
            "memory": {
                "total": vm.total, "available": vm.available, "percent": vm.percent,
            },
            "disk": {
                "/": {
                    "total": psutil.disk_usage("/").total,
                    "used": psutil.disk_usage("/").used,
                    "percent": psutil.disk_usage("/").percent,
                }
            },
            "boot_time": psutil.boot_time(),
            "process_count": len(psutil.pids()),
        }
        return SkillResult(ok=True, data=info)


registry.register(TerminalExecSkill())
registry.register(SystemInfoSkill())
