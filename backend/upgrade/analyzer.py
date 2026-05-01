"""Code analyzer for the upgrade pipeline.

Walks `backend/` and produces a compact representation that fits inside a
prompt — file sizes, top-level symbols, recent telemetry hints. The Coder
agent uses this to propose targeted improvements rather than blind rewrites.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from backend.config import settings


def walk_backend() -> dict[str, Any]:
    root = settings.root / "backend"
    files: list[dict[str, Any]] = []
    total = 0
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        size = len(src)
        total += size
        files.append({
            "path": str(p.relative_to(settings.root)),
            "size": size,
            "lines": src.count("\n"),
            "symbols": _top_symbols(src),
        })
    return {"total_bytes": total, "file_count": len(files), "files": files}


def _top_symbols(src: str) -> list[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(f"def {node.name}")
        elif isinstance(node, ast.ClassDef):
            out.append(f"class {node.name}")
    return out


def summary_text() -> str:
    """Human-readable summary suitable as a prompt prefix."""
    data = walk_backend()
    return (
        f"Backend has {data['file_count']} python files, "
        f"{data['total_bytes']} bytes total.\n"
        + json.dumps(data["files"], indent=2)[:6000]
    )
