"""Terminal execution with permission gating.

Streams stdout/stderr to the event bus so the UI can show live output.
Dangerous commands (rm, sudo, dd, mkfs, format, shutdown, reboot) are gated.
"""
from __future__ import annotations

import asyncio
import os
import shlex
from dataclasses import dataclass

from backend.config import settings
from backend.core.events import bus
from backend.core.logger import logger
from backend.system.permissions import permissions


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_s: float


class Terminal:
    async def run(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: float = 600.0,
        admin: bool = False,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        if not settings.allow_terminal:
            raise PermissionError("Terminal access is disabled in settings.")

        full_cmd = f"sudo -n {command}" if admin else command
        dangerous = admin or permissions.is_command_dangerous(command)

        async def _exec() -> CommandResult:
            return await self._run_streaming(full_cmd, cwd=cwd, timeout=timeout, env=env)

        return await permissions.gate(
            kind="terminal.exec",
            description=f"$ {full_cmd}",
            dangerous=dangerous,
            payload={"command": full_cmd, "cwd": cwd, "admin": admin},
            run=_exec,
        )

    async def _run_streaming(
        self,
        command: str,
        *,
        cwd: str | None,
        timeout: float,
        env: dict[str, str] | None,
    ) -> CommandResult:
        import time
        t0 = time.perf_counter()
        await bus.publish("terminal", {"type": "start", "command": command})

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            env={**os.environ, **(env or {})},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        async def pump(stream: asyncio.StreamReader, kind: str, sink: list[str]) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace")
                sink.append(text)
                await bus.publish("terminal", {"type": kind, "line": text.rstrip()})

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    pump(proc.stdout, "stdout", stdout_chunks) if proc.stdout else asyncio.sleep(0),
                    pump(proc.stderr, "stderr", stderr_chunks) if proc.stderr else asyncio.sleep(0),
                    proc.wait(),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await bus.publish("terminal", {"type": "timeout", "command": command})
            raise

        rc = proc.returncode if proc.returncode is not None else -1
        result = CommandResult(
            command=command,
            returncode=rc,
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
            duration_s=time.perf_counter() - t0,
        )
        await bus.publish(
            "terminal",
            {"type": "end", "command": command, "returncode": rc, "duration_s": result.duration_s},
        )
        logger.info(f"$ {command} -> rc={rc} ({result.duration_s:.2f}s)")
        return result

    async def open_admin_terminal(self) -> CommandResult:
        """Open an interactive admin shell. Requires explicit user approval."""
        # Detect platform
        cmd = "sudo -i" if os.name == "posix" else "powershell Start-Process powershell -Verb RunAs"
        return await self.run(cmd, admin=True, timeout=10)


terminal = Terminal()


def safe_split(cmd: str) -> list[str]:
    """Helper for callers that want shlex split."""
    return shlex.split(cmd)
