"""Lightweight sandbox helpers for risky commands.

Two strategies:
  - dry_run:  prepend `echo` so the command is logged but not executed
  - chroot-ish: run inside `./data/sandbox` cwd (best-effort)

Real isolation requires Docker / Firejail; we expose hooks but don't
require them. The important contract is: when SANDBOX_DANGEROUS is true
and a command is flagged risky, it is wrapped here before execution.
"""
from __future__ import annotations

import os
from pathlib import Path

from backend.config import settings


SANDBOX_ROOT = Path("./data/sandbox").resolve()


def ensure_sandbox_dir() -> Path:
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    return SANDBOX_ROOT


def wrap_command(cmd: str, *, dangerous: bool) -> tuple[str, str | None]:
    """Return (wrapped_command, cwd). Only wraps when sandbox is enabled."""
    if not (dangerous and settings.sandbox_dangerous):
        return cmd, None

    sandbox_dir = ensure_sandbox_dir()

    # Prefer firejail if available
    if _which("firejail"):
        return f"firejail --quiet --private={sandbox_dir} {cmd}", str(sandbox_dir)

    # Fallback: just constrain CWD
    return cmd, str(sandbox_dir)


def _which(prog: str) -> bool:
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if (Path(p) / prog).exists():
            return True
    return False
