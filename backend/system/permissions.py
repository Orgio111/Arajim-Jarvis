"""Permission gating layer for OS-level actions.

Every dangerous action goes through here. The mode controller decides whether
a confirmation is required; if so, the action is queued and the UI must
approve it via /api/confirm/<id>.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from backend.config import settings
from backend.core.events import bus
from backend.core.logger import logger
from backend.core.modes import controller as mode_ctrl


@dataclass
class PendingAction:
    id: str
    kind: str
    description: str
    payload: dict[str, Any]
    created_at: float
    future: asyncio.Future = field(repr=False, default_factory=asyncio.Future)


class PermissionDenied(Exception):
    pass


class PermissionManager:
    def __init__(self) -> None:
        self._pending: dict[str, PendingAction] = {}

    # ------------------------------------------------------------- detection
    @staticmethod
    def is_command_dangerous(cmd: str) -> bool:
        lower = cmd.lower()
        for kw in settings.confirm_keywords:
            if kw and kw in lower.split() or f" {kw} " in f" {lower} ":
                return True
            if kw and lower.startswith(kw):
                return True
        return False

    @staticmethod
    def is_path_dangerous(path: str) -> bool:
        risky = ["/etc", "/boot", "/sys", "/proc", "/usr", "/var", "C:\\Windows", "C:\\Program"]
        return any(path.startswith(r) for r in risky)

    # ----------------------------------------------------------- core gating
    async def gate(
        self,
        *,
        kind: str,
        description: str,
        dangerous: bool,
        payload: dict[str, Any] | None = None,
        run: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Run an action through permission gating."""
        needs = mode_ctrl.needs_confirmation(dangerous=dangerous)
        if not needs:
            logger.info(f"[permit-auto] {kind}: {description}")
            await bus.publish("action", {"type": "auto", "kind": kind, "desc": description})
            return await run()

        # Need confirmation
        action = PendingAction(
            id=str(uuid.uuid4()),
            kind=kind,
            description=description,
            payload=payload or {},
            created_at=time.time(),
        )
        self._pending[action.id] = action
        await bus.publish(
            "action",
            {
                "type": "pending",
                "id": action.id,
                "kind": kind,
                "desc": description,
                "payload": payload or {},
            },
        )
        logger.info(f"[permit-pending] {kind}: {description} (id={action.id})")
        approved = await action.future
        self._pending.pop(action.id, None)
        if not approved:
            raise PermissionDenied(f"User denied {kind}: {description}")
        return await run()

    def approve(self, action_id: str) -> bool:
        action = self._pending.get(action_id)
        if not action or action.future.done():
            return False
        action.future.set_result(True)
        return True

    def deny(self, action_id: str) -> bool:
        action = self._pending.get(action_id)
        if not action or action.future.done():
            return False
        action.future.set_result(False)
        return True

    @property
    def pending(self) -> list[dict[str, Any]]:
        return [
            {
                "id": a.id,
                "kind": a.kind,
                "description": a.description,
                "payload": a.payload,
                "created_at": a.created_at,
            }
            for a in self._pending.values()
        ]


permissions = PermissionManager()
