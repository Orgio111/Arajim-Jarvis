"""REST endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from backend.agents.orchestrator import orchestrator
from backend.config import settings
from backend.core.modes import Mode, controller as mode_ctrl
from backend.memory.store import get_store
from backend.nvidia.benchmark import benchmark_all
from backend.nvidia.client import get_client
from backend.nvidia.models import MODEL_REGISTRY
from backend.nvidia.router import router as model_router
from backend.skills.registry import registry as skill_registry
from backend.system.permissions import permissions
from backend.upgrade.manager import UpgradeError, upgrade_manager
from backend.voice.pipeline import voice as voice_pipeline

router = APIRouter()


# ----------------------------------------------------------------- chat
class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str


@router.post("/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    # Special trigger: upgrade myself
    if upgrade_manager.is_trigger(req.message):
        try:
            result = await upgrade_manager.upgrade(requested_by=req.session_id)
            return {"reply": f"Upgrade applied: v{result['version']} — {result['summary']}",
                    "plan": None, "results": [], "upgrade": result}
        except UpgradeError as exc:
            raise HTTPException(400, str(exc))
    return await orchestrator.handle(session_id=req.session_id, user_message=req.message)


# ----------------------------------------------------------------- memory
@router.get("/memory")
async def list_memories(limit: int = 100):
    return {"memories": await get_store().list_memories(limit=limit)}


@router.post("/memory")
async def add_memory(item: dict[str, Any]):
    mid = await get_store().remember(item.get("content", ""), tags=item.get("tags"))
    return {"id": mid}


@router.delete("/memory/{mid}")
async def delete_memory(mid: int):
    ok = await get_store().forget(mid)
    if not ok:
        raise HTTPException(404, "memory not found")
    return {"deleted": True}


@router.get("/sessions")
async def sessions():
    return {"sessions": await get_store().list_sessions()}


@router.get("/sessions/{session_id}")
async def session_history(session_id: str):
    return {"messages": await get_store().get_chat(session_id)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    n = await get_store().delete_chat(session_id)
    return {"deleted": n}


# ----------------------------------------------------------------- mode
@router.get("/mode")
async def get_mode():
    return {"mode": mode_ctrl.mode.value}


@router.post("/mode")
async def set_mode(item: dict[str, str]):
    try:
        mode_ctrl.set(Mode(item["mode"]))
    except (KeyError, ValueError):
        raise HTTPException(400, "invalid mode")
    return {"mode": mode_ctrl.mode.value}


# -------------------------------------------------------- permissions
@router.get("/permissions/pending")
async def pending_permissions():
    return {"pending": permissions.pending}


@router.post("/permissions/{action_id}/approve")
async def approve(action_id: str):
    ok = permissions.approve(action_id)
    if not ok:
        raise HTTPException(404, "action not pending")
    return {"approved": True}


@router.post("/permissions/{action_id}/deny")
async def deny(action_id: str):
    ok = permissions.deny(action_id)
    if not ok:
        raise HTTPException(404, "action not pending")
    return {"denied": True}


# ---------------------------------------------------------- nvidia/models
@router.get("/models")
async def models():
    return {
        "registry": {
            mid: {
                "id": m.id, "tier": m.tier.value, "context_window": m.context_window,
                "strengths": list(m.strengths), "supports_tools": m.supports_tools,
                "notes": m.notes,
            }
            for mid, m in MODEL_REGISTRY.items()
        },
        "scores": model_router.scores,
        "stats": get_client().stats,
    }


@router.get("/models/live")
async def models_live():
    return {"available": await get_client().list_models()}


@router.post("/benchmark")
async def benchmark():
    return {"results": await benchmark_all()}


# ----------------------------------------------------------------- skills
@router.get("/skills")
async def skills():
    return {"skills": skill_registry.descriptions()}


class SkillInvoke(BaseModel):
    name: str
    args: dict[str, Any] = {}


@router.post("/skills/invoke")
async def invoke_skill(req: SkillInvoke):
    res = await skill_registry.invoke(req.name, **req.args)
    return {"ok": res.ok, "data": res.data, "error": res.error}


# ---------------------------------------------------------------- upgrade
@router.get("/upgrade/versions")
async def upgrade_versions():
    return {"versions": upgrade_manager.list(), "current": next(
        (v for v in upgrade_manager.list() if v.get("status") == "applied"), None)}


@router.post("/upgrade")
async def upgrade(req: dict[str, str] | None = None):
    """Triggered by user clicking Upgrade Myself or typing the phrase."""
    confirm = (req or {}).get("phrase", "")
    if not upgrade_manager.is_trigger(confirm):
        raise HTTPException(400, f"Confirmation phrase required: '{settings.upgrade_confirm_phrase}'")
    try:
        return await upgrade_manager.upgrade(requested_by="ui")
    except UpgradeError as exc:
        raise HTTPException(409, str(exc))


@router.post("/upgrade/rollback")
async def rollback(req: dict[str, int] | None = None):
    target = (req or {}).get("version")
    try:
        return await upgrade_manager.rollback(target)
    except UpgradeError as exc:
        raise HTTPException(400, str(exc))


# ----------------------------------------------------------------- voice
@router.post("/voice/transcribe")
async def voice_transcribe(audio: UploadFile = File(...), language: str = Form(default="")):
    data = await audio.read()
    text = await voice_pipeline.transcribe(data, language=language or None)
    return {"text": text}


@router.post("/voice/speak")
async def voice_speak(item: dict[str, str]):
    audio = await voice_pipeline.synth(item.get("text", ""), voice=item.get("voice"))
    return {"bytes": len(audio)}


@router.post("/voice/toggle")
async def voice_toggle(item: dict[str, bool] | None = None):
    state = voice_pipeline.toggle((item or {}).get("on"))
    return {"active": state}


@router.get("/voice/state")
async def voice_state():
    return {
        "enabled": voice_pipeline.enabled,
        "active": voice_pipeline.active,
        "lang": settings.voice_lang,
    }


# ----------------------------------------------------------------- health
@router.get("/health")
async def health():
    return {
        "ok": True,
        "version": next(
            (v["version"] for v in upgrade_manager.list() if v.get("status") == "applied"), 1
        ),
        "mode": mode_ctrl.mode.value,
        "nvidia_configured": bool(settings.nvidia_api_key),
    }
