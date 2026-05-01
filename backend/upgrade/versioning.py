"""Versioning store for self-upgrades.

Each upgrade creates `versions/v<N>/` containing:
  - snapshot/      full backup of `backend/` before the upgrade
  - changelog.md   human-readable summary of changes
  - manifest.json  metadata: timestamp, files changed, model used, status
  - patch.diff     unified diff against the previous version

Rollback restores `snapshot/` over `backend/` and decrements CURRENT_VERSION.
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.core.logger import logger

UPGRADE_ROOT = Path(settings.upgrade_dir)


@dataclass
class VersionManifest:
    version: int
    timestamp: float
    parent_version: int | None
    status: str  # pending | applied | rolled_back | failed
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    model_used: str = ""
    notes: str = ""


def list_versions() -> list[dict[str, Any]]:
    if not UPGRADE_ROOT.exists():
        return []
    out = []
    for d in sorted(UPGRADE_ROOT.glob("v*")):
        man = d / "manifest.json"
        if man.exists():
            out.append(json.loads(man.read_text()))
    return out


def current_version() -> int:
    versions = list_versions()
    applied = [v for v in versions if v.get("status") == "applied"]
    if applied:
        return max(v["version"] for v in applied)
    return settings.current_version


def next_version() -> int:
    return current_version() + 1


def version_dir(n: int) -> Path:
    return UPGRADE_ROOT / f"v{n}"


def create_snapshot(version: int) -> Path:
    """Snapshot the current backend/ tree."""
    src = settings.root / "backend"
    dst = version_dir(version) / "snapshot"
    dst.mkdir(parents=True, exist_ok=True)
    # Skip __pycache__
    for path in src.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    logger.info(f"Snapshot saved: {dst}")
    return dst


def write_manifest(version: int, manifest: VersionManifest) -> None:
    p = version_dir(version) / "manifest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(manifest), indent=2))


def write_changelog(version: int, text: str) -> None:
    p = version_dir(version) / "changelog.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def restore_snapshot(version: int) -> bool:
    """Restore the snapshot of the GIVEN version over backend/."""
    src = version_dir(version) / "snapshot"
    if not src.exists():
        return False
    dst = settings.root / "backend"
    # Wipe target then copy back (preserving virtualenvs / data outside backend/)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    logger.warning(f"Restored backend/ from {src}")
    return True


def update_status(version: int, status: str, **fields: Any) -> None:
    p = version_dir(version) / "manifest.json"
    if not p.exists():
        return
    data = json.loads(p.read_text())
    data["status"] = status
    data.update(fields)
    p.write_text(json.dumps(data, indent=2))


def init_v1_if_missing() -> None:
    """Make sure v1 exists as the baseline so we can always roll back to it."""
    if version_dir(1).exists():
        return
    create_snapshot(1)
    write_manifest(
        1,
        VersionManifest(
            version=1,
            timestamp=time.time(),
            parent_version=None,
            status="applied",
            summary="Initial baseline",
            files_changed=[],
            notes="Auto-created baseline snapshot.",
        ),
    )
    write_changelog(1, "# v1\nInitial baseline. No changes.\n")
