"""Self-upgrade orchestrator.

CRITICAL CONTRACT:
  - The system MUST NOT modify itself automatically.
  - Self-improvement runs ONLY when the user explicitly types the configured
    confirmation phrase (default: "upgrade myself").
  - Every upgrade creates a new version (v2, v3, ...) with a snapshot,
    changelog, manifest, and patch. Rollback restores the previous version.

Pipeline (when triggered):
  1. Snapshot current backend/ -> versions/v<N>/snapshot/
  2. Analyze code (analyzer.summary_text)
  3. Reasoning model proposes structured improvements (JSON list of patches)
  4. Coder model emits exact file rewrites
  5. Reviewer model validates each patch
  6. ONLY validated patches are applied; failures abort the upgrade
  7. Smoke-test: import backend modules
  8. Mark version "applied" or roll back automatically on failure
"""
from __future__ import annotations

import importlib
import json
import re
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.core.events import bus
from backend.core.logger import logger
from backend.nvidia.client import get_client
from backend.nvidia.router import router
from backend.upgrade import analyzer, versioning
from backend.upgrade.versioning import (
    VersionManifest,
    create_snapshot,
    current_version,
    init_v1_if_missing,
    list_versions,
    next_version,
    restore_snapshot,
    update_status,
    version_dir,
    write_changelog,
    write_manifest,
)


PROPOSAL_SYSTEM = (
    "You are JARVIS-Architect. You analyze a Python codebase and propose "
    "minimal, safe improvements. NEVER break public function signatures. "
    "NEVER touch the upgrade module itself.\n\n"
    "Output strict JSON:\n"
    "{\n"
    '  "summary": "short title",\n'
    '  "patches": [\n'
    '    {"path": "backend/...", "intent": "...", "rationale": "..."},\n'
    "    ...\n"
    "  ]\n"
    "}\n"
    "Limit to 1-3 patches per upgrade. Pick high-impact, low-risk targets."
)

REWRITE_SYSTEM = (
    "You are JARVIS-Coder. You will rewrite ONE Python file. "
    "Return strict JSON: {\"path\": \"...\", \"content\": \"<full new file content>\"}. "
    "Preserve all imports and public interfaces. Improve clarity, performance, "
    "type hints, error handling. Do NOT introduce new dependencies."
)

REVIEW_SYSTEM = (
    "You are JARVIS-Reviewer. Validate the proposed file rewrite is safe. "
    "Return strict JSON: {\"approve\": bool, \"issues\": [..]}. "
    "Reject if it removes public symbols, changes signatures, or looks wrong."
)


PROTECTED = {
    "backend/upgrade/manager.py",
    "backend/upgrade/versioning.py",
    "backend/upgrade/__init__.py",
    "backend/config.py",
    "backend/main.py",
}


class UpgradeError(Exception):
    pass


class UpgradeManager:
    def __init__(self) -> None:
        self._busy = False
        init_v1_if_missing()

    @property
    def is_busy(self) -> bool:
        return self._busy

    def is_trigger(self, text: str) -> bool:
        """Strict trigger check — only the user can start an upgrade."""
        if not text:
            return False
        return text.strip().lower() == settings.upgrade_confirm_phrase.strip().lower()

    # ============================================================== upgrade
    async def upgrade(self, *, requested_by: str = "user") -> dict[str, Any]:
        if self._busy:
            raise UpgradeError("An upgrade is already in progress.")
        self._busy = True
        version = next_version()
        await bus.publish("upgrade", {"type": "started", "version": version})
        logger.warning(f"=== Self-upgrade v{version} started by {requested_by} ===")

        manifest = VersionManifest(
            version=version,
            timestamp=time.time(),
            parent_version=current_version(),
            status="pending",
        )

        try:
            # 1) snapshot
            create_snapshot(version)
            write_manifest(version, manifest)
            await bus.publish("upgrade", {"type": "snapshot_done", "version": version})

            # 2) propose
            proposal = await self._propose()
            manifest.summary = proposal.get("summary", "")
            manifest.model_used = proposal.get("_model", "")
            await bus.publish("upgrade", {"type": "proposal", "data": proposal})

            patches_applied: list[dict[str, Any]] = []
            for patch in proposal.get("patches", []):
                path = patch.get("path", "")
                if path in PROTECTED:
                    logger.warning(f"Skipping protected file: {path}")
                    continue
                if not path.startswith("backend/") or not path.endswith(".py"):
                    continue
                # 3) rewrite
                rewrite = await self._rewrite_file(patch)
                # 4) review
                review = await self._review_rewrite(rewrite)
                if not review.get("approve"):
                    logger.warning(f"Reviewer rejected {path}: {review.get('issues')}")
                    continue
                # 5) apply
                self._apply_rewrite(rewrite)
                patches_applied.append({
                    "path": path,
                    "intent": patch.get("intent", ""),
                    "issues": review.get("issues", []),
                })
                manifest.files_changed.append(path)
                await bus.publish("upgrade", {"type": "patch_applied", "path": path})

            if not patches_applied:
                raise UpgradeError("No patches were approved.")

            # 6) smoke test
            self._smoke_test()

            # 7) finalize
            manifest.status = "applied"
            manifest.notes = f"Applied {len(patches_applied)} patch(es)."
            write_manifest(version, manifest)
            write_changelog(version, self._format_changelog(version, proposal, patches_applied))

            await bus.publish("upgrade", {"type": "applied", "version": version})
            logger.warning(f"=== Self-upgrade v{version} applied ===")
            return {"version": version, "patches": patches_applied, "summary": manifest.summary}

        except Exception as exc:
            logger.exception("Upgrade failed; rolling back.")
            tb = traceback.format_exc()
            try:
                restore_snapshot(current_version())
            except Exception as inner:
                logger.error(f"Rollback also failed: {inner}")
            update_status(version, "failed", notes=f"{exc}\n{tb[:1000]}")
            await bus.publish("upgrade", {"type": "failed", "version": version, "error": str(exc)})
            raise
        finally:
            self._busy = False

    # ============================================================ rollback
    async def rollback(self, target_version: int | None = None) -> dict[str, Any]:
        target = target_version if target_version is not None else (current_version() - 1)
        if target < 1:
            raise UpgradeError("Cannot rollback below v1.")
        if not version_dir(target).exists():
            raise UpgradeError(f"Version v{target} not found.")
        ok = restore_snapshot(target)
        if not ok:
            raise UpgradeError(f"Rollback to v{target} failed: snapshot missing.")
        update_status(current_version(), "rolled_back")
        await bus.publish("upgrade", {"type": "rolled_back", "to": target})
        logger.warning(f"Rolled back to v{target}")
        return {"rolled_back_to": target}

    # ================================================================ list
    def list(self) -> list[dict[str, Any]]:
        return list_versions()

    # ============================================================= internals
    async def _propose(self) -> dict[str, Any]:
        client = get_client()
        model = router.pick_for("planner", prefer_quality=True)
        summary = analyzer.summary_text()
        resp = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": PROPOSAL_SYSTEM},
                {"role": "user", "content": summary},
            ],
            max_tokens=2048,
            temperature=0.4,
            thinking=True,
        )
        text = resp.choices[0].message.content or ""
        data = self._extract_json(text) or {"summary": "no-op", "patches": []}
        data["_model"] = model
        return data

    async def _rewrite_file(self, patch: dict[str, Any]) -> dict[str, Any]:
        client = get_client()
        model = router.pick_for("coder", prefer_quality=True)
        path = patch["path"]
        try:
            current = (settings.root / path).read_text()
        except Exception as exc:
            raise UpgradeError(f"Cannot read {path}: {exc}")
        prompt = (
            f"Intent: {patch.get('intent','')}\n"
            f"Rationale: {patch.get('rationale','')}\n\n"
            f"File path: {path}\n"
            f"Current contents:\n```python\n{current}\n```\n\n"
            "Rewrite the entire file to satisfy the intent. Return JSON only."
        )
        resp = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=8192,
            temperature=0.2,
        )
        text = resp.choices[0].message.content or ""
        rewrite = self._extract_json(text)
        if not rewrite or "content" not in rewrite or "path" not in rewrite:
            raise UpgradeError(f"Rewriter produced unparseable output for {path}")
        rewrite["_old"] = current
        return rewrite

    async def _review_rewrite(self, rewrite: dict[str, Any]) -> dict[str, Any]:
        client = get_client()
        model = router.pick_for("reviewer", prefer_quality=True)
        prompt = (
            f"Path: {rewrite['path']}\n\nOLD:\n```python\n{rewrite['_old'][:6000]}\n```\n\n"
            f"NEW:\n```python\n{rewrite['content'][:6000]}\n```\n\n"
            "Validate. Reject if public symbols are removed."
        )
        resp = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=512,
            temperature=0.0,
            thinking=True,
        )
        text = resp.choices[0].message.content or ""
        review = self._extract_json(text)
        if review is None:
            return {"approve": False, "issues": ["unparseable reviewer output"]}

        # Lightweight guard: ensure new file parses as Python
        try:
            compile(rewrite["content"], rewrite["path"], "exec")
        except SyntaxError as exc:
            review["approve"] = False
            review.setdefault("issues", []).append(f"syntax error: {exc}")
        return review

    def _apply_rewrite(self, rewrite: dict[str, Any]) -> None:
        path = settings.root / rewrite["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rewrite["content"])

    def _smoke_test(self) -> None:
        """Re-import critical modules to confirm syntax + import-time correctness."""
        for mod in [
            "backend.nvidia.client",
            "backend.nvidia.router",
            "backend.agents.orchestrator",
            "backend.skills.registry",
            "backend.memory.store",
        ]:
            m = importlib.import_module(mod)
            importlib.reload(m)
        logger.info("Smoke test passed.")

    @staticmethod
    def _format_changelog(
        version: int,
        proposal: dict[str, Any],
        applied: list[dict[str, Any]],
    ) -> str:
        lines = [f"# v{version}", "", proposal.get("summary", ""), "", "## Patches applied"]
        for p in applied:
            lines.append(f"- **{p['path']}** — {p['intent']}")
            for issue in p.get("issues", []):
                lines.append(f"    - reviewer note: {issue}")
        lines += ["", "## Files changed", *(f"- {p['path']}" for p in applied)]
        return "\n".join(lines)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence:
            try:
                return json.loads(fence.group(1))
            except json.JSONDecodeError:
                pass
        brace = re.search(r"(\{.*\})", text, re.DOTALL)
        if brace:
            try:
                return json.loads(brace.group(1))
            except json.JSONDecodeError:
                return None
        return None


upgrade_manager = UpgradeManager()
