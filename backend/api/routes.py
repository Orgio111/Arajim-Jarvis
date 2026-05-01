"""REST endpoints."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.auth import auth_dependency

from backend.agents.collaboration import collaboration
from backend.agents.orchestrator import orchestrator
from backend.cache.manager import cache
from backend.config import settings
from backend.core.modes import Mode, controller as mode_ctrl
from backend.intelligence.intent import predict_intent
from backend.learning.passive import learner
from backend.memory.store import get_store
from backend.nvidia.benchmark import benchmark_all
from backend.nvidia.client import get_client
from backend.nvidia.models import MODEL_REGISTRY
from backend.nvidia.router import router as model_router
from backend.search.deep import deep_search
from backend.search.web import web_search
from backend.skills.registry import registry as skill_registry
from backend.system.permissions import permissions
from backend.upgrade.manager import UpgradeError, upgrade_manager
from backend.vector.store import get_vector_store
from backend.voice.pipeline import voice as voice_pipeline

router = APIRouter(dependencies=[Depends(auth_dependency)])


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


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Server-Sent Events: token-by-token streaming for chat intents."""

    async def gen():
        try:
            async for chunk in orchestrator.handle_stream(
                session_id=req.session_id, user_message=req.message
            ):
                yield f"data: {json.dumps(chunk, default=str)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'event': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    """Synthesize and return audio bytes (audio/mpeg)."""
    audio = await voice_pipeline.synth(item.get("text", ""), voice=item.get("voice"))
    from fastapi.responses import Response
    return Response(content=audio, media_type="audio/mpeg",
                    headers={"X-Audio-Bytes": str(len(audio))})


@router.post("/voice/converse")
async def voice_converse(audio: UploadFile = File(...),
                          session_id: str = Form(default="voice"),
                          language: str = Form(default="")):
    """Full loop: mic audio in → JARVIS reply audio out."""
    data = await audio.read()
    result = await voice_pipeline.handle_audio(data, session_id=session_id)
    from fastapi.responses import Response
    return Response(
        content=result["audio"],
        media_type="audio/mpeg",
        headers={
            "X-Transcript": result["text"][:512],
            "X-Reply": result["reply"][:512],
        },
    )


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


# ------------------------------------------------ NVIDIA parallel + merge
class RaceReq(BaseModel):
    prompt: str
    models: list[str] | None = None
    max_tokens: int = 1024


@router.post("/models/race")
async def models_race(req: RaceReq):
    """Send the same prompt to N models concurrently, return whichever wins."""
    client = get_client()
    models = req.models or [m for m in MODEL_REGISTRY][:3]
    msgs = [{"role": "user", "content": req.prompt}]
    winner = await client.race(models=models, messages=msgs, max_tokens=req.max_tokens)
    return {"answer": winner.choices[0].message.content,
            "models_raced": models}


class MergeReq(BaseModel):
    prompt: str
    models: list[str] | None = None
    max_tokens: int = 1024


@router.post("/models/merge_best")
async def models_merge_best(req: MergeReq):
    """Run prompt across N models in parallel, pick highest-quality reply.

    Quality is judged by a fast NIM reviewer model so we still leverage
    the brief's best-result merging without a learned scorer.
    """
    import asyncio
    client = get_client()
    models = req.models or [m for m in MODEL_REGISTRY][:3]
    msgs = [{"role": "user", "content": req.prompt}]
    answers = await asyncio.gather(
        *(client.chat(model=m, messages=msgs, max_tokens=req.max_tokens) for m in models),
        return_exceptions=True,
    )
    candidates = []
    for m, a in zip(models, answers):
        if isinstance(a, Exception):
            continue
        candidates.append({"model": m, "text": a.choices[0].message.content})
    if not candidates:
        raise HTTPException(502, "all models failed")

    # Reviewer picks the best
    judge_prompt = (
        "You will pick the strongest answer to the user's question.\n"
        f"Question: {req.prompt}\n\nCandidates:\n"
        + "\n\n".join(f"[{i+1}] ({c['model']})\n{c['text']}" for i, c in enumerate(candidates))
        + "\n\nReply with ONLY the integer of the best candidate."
    )
    judge = await client.chat(
        model=model_router.pick_for("reviewer", prefer_quality=True),
        messages=[{"role": "user", "content": judge_prompt}],
        max_tokens=8, temperature=0.0,
    )
    pick_text = (judge.choices[0].message.content or "1").strip()
    import re
    m = re.search(r"\d+", pick_text)
    idx = (int(m.group(0)) - 1) if m else 0
    idx = max(0, min(idx, len(candidates) - 1))
    return {"winner": candidates[idx], "candidates": candidates}


# ----------------------------------------------------------------- intent
@router.post("/intent")
async def intent(item: dict[str, str]):
    res = await predict_intent(item.get("message", ""))
    return res.__dict__


# ----------------------------------------------------------------- search
class SearchReq(BaseModel):
    query: str
    k: int = 6


@router.post("/search/web")
async def web_search_route(req: SearchReq):
    rs = await web_search(req.query, k=req.k)
    return {"results": [{"title": r.title, "url": r.url, "snippet": r.snippet,
                          "source": r.source} for r in rs]}


class DeepSearchReq(BaseModel):
    question: str
    max_steps: int | None = None


@router.post("/search/deep")
async def deep_search_route(req: DeepSearchReq):
    r = await deep_search(req.question, max_steps=req.max_steps)
    return {
        "answer": r.answer,
        "citations": r.citations,
        "steps": r.steps,
        "elapsed_s": r.elapsed_s,
    }


# ----------------------------------------------------------------- cache
@router.get("/cache/stats")
async def cache_stats():
    return cache.stats


@router.post("/cache/invalidate")
async def cache_invalidate(item: dict[str, str]):
    await cache.invalidate(item.get("namespace", "chat-reply"))
    return {"ok": True}


# ----------------------------------------------------------- vector memory
@router.get("/vector/size")
async def vector_size():
    return {"size": get_vector_store().size}


class VectorSearch(BaseModel):
    query: str
    k: int = 6
    threshold: float = 0.0


@router.post("/vector/search")
async def vector_search(req: VectorSearch):
    return {"hits": await get_vector_store().search(req.query, k=req.k,
                                                     threshold=req.threshold)}


# ----------------------------------------------------------------- learning
@router.get("/learning")
async def learning():
    return learner.snapshot()


# --------------------------------------------------------------- debate API
class DebateReq(BaseModel):
    task: str
    language: str = "python"
    max_rounds: int = 3


@router.post("/agents/debate")
async def debate(req: DebateReq):
    r = await collaboration.debate(req.task, language=req.language,
                                    max_rounds=req.max_rounds)
    return {
        "final": r.final,
        "rounds": [{"n": rd.n, "score": rd.score, "review": rd.review}
                   for rd in r.rounds],
        "elapsed_s": r.elapsed_s,
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
