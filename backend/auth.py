"""Optional bearer-token auth for the API.

Activated by setting `JARVIS_AUTH_TOKEN` in the environment. If unset, the
API is open (intended for localhost dev). When set, every /api/* request
must carry `Authorization: Bearer <token>`.

Loopback connections (127.0.0.1, ::1) are exempted by default unless
`JARVIS_AUTH_STRICT=true` — useful for letting the local Vite dev server
hit the API while still requiring auth from external callers.
"""
from __future__ import annotations

import os
from fastapi import HTTPException, Request

_TOKEN = os.environ.get("JARVIS_AUTH_TOKEN", "").strip()
_STRICT = os.environ.get("JARVIS_AUTH_STRICT", "false").lower() == "true"


def is_enabled() -> bool:
    return bool(_TOKEN)


async def auth_dependency(request: Request) -> None:
    """FastAPI dependency. Raises 401 when token is required and missing."""
    if not _TOKEN:
        return
    if not _STRICT:
        client_host = (request.client.host if request.client else "") or ""
        if client_host in {"127.0.0.1", "::1", "localhost"}:
            return
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    if header.split(" ", 1)[1].strip() != _TOKEN:
        raise HTTPException(401, "Invalid bearer token")
