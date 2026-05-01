"""Filesystem operations with permission gating."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.core.events import bus
from backend.system.permissions import permissions


class FileSystem:
    async def read(self, path: str, *, max_bytes: int = 2_000_000) -> str:
        if not settings.allow_filesystem:
            raise PermissionError("Filesystem access disabled.")
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(path)
        async def _do() -> str:
            data = p.read_bytes()[:max_bytes]
            return data.decode(errors="replace")
        return await permissions.gate(
            kind="fs.read",
            description=f"read {p}",
            dangerous=False,
            payload={"path": str(p)},
            run=_do,
        )

    async def write(self, path: str, content: str, *, append: bool = False) -> int:
        if not settings.allow_filesystem:
            raise PermissionError("Filesystem access disabled.")
        p = Path(path).expanduser().resolve()
        dangerous = permissions.is_path_dangerous(str(p))
        async def _do() -> int:
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "ab" if append else "wb"
            with open(p, mode) as f:
                n = f.write(content.encode())
            await bus.publish("fs", {"type": "write", "path": str(p), "bytes": n})
            return n
        return await permissions.gate(
            kind="fs.write",
            description=f"{'append' if append else 'write'} {p} ({len(content)}B)",
            dangerous=dangerous,
            payload={"path": str(p), "append": append, "size": len(content)},
            run=_do,
        )

    async def delete(self, path: str) -> bool:
        if not settings.allow_filesystem:
            raise PermissionError("Filesystem access disabled.")
        p = Path(path).expanduser().resolve()
        async def _do() -> bool:
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
            else:
                return False
            await bus.publish("fs", {"type": "delete", "path": str(p)})
            return True
        return await permissions.gate(
            kind="fs.delete",
            description=f"delete {p}",
            dangerous=True,  # always confirm deletes outside full_auto
            payload={"path": str(p)},
            run=_do,
        )

    async def list(self, path: str = ".") -> list[dict[str, Any]]:
        if not settings.allow_filesystem:
            raise PermissionError("Filesystem access disabled.")
        p = Path(path).expanduser().resolve()
        out: list[dict[str, Any]] = []
        for child in sorted(p.iterdir()):
            try:
                st = child.stat()
                out.append({
                    "name": child.name,
                    "path": str(child),
                    "is_dir": child.is_dir(),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                })
            except OSError:
                continue
        return out

    async def move(self, src: str, dst: str) -> str:
        sp = Path(src).expanduser().resolve()
        dp = Path(dst).expanduser().resolve()
        async def _do() -> str:
            shutil.move(str(sp), str(dp))
            return str(dp)
        return await permissions.gate(
            kind="fs.move", description=f"mv {sp} -> {dp}",
            dangerous=permissions.is_path_dangerous(str(dp)),
            payload={"src": str(sp), "dst": str(dp)}, run=_do,
        )


fs = FileSystem()
