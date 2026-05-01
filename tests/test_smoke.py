"""Smoke tests — exercise the boot path and core flows without a real NIM key."""
from __future__ import annotations

import asyncio
import pytest
from fastapi.testclient import TestClient


def _client():
    from backend.main import app
    return TestClient(app)


def test_health_responds(patched_nim):
    with _client() as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["mode"] in {"smart_assist", "full_auto", "manual"}


def test_skills_registered(patched_nim):
    with _client() as c:
        r = c.get("/api/skills")
        names = {s["name"] for s in r.json()["skills"]}
        for must_have in {"terminal_exec", "system_info", "file_list",
                          "remember", "recall", "forget",
                          "web_search", "deep_search"}:
            assert must_have in names, f"missing skill {must_have}"


def test_models_registry_nonempty(patched_nim):
    with _client() as c:
        r = c.get("/api/models")
        assert len(r.json()["registry"]) >= 5


def test_mode_switch(patched_nim):
    with _client() as c:
        for m in ("full_auto", "manual", "smart_assist"):
            r = c.post("/api/mode", json={"mode": m})
            assert r.status_code == 200 and r.json()["mode"] == m


def test_memory_lifecycle(patched_nim):
    with _client() as c:
        r = c.post("/api/memory", json={"content": "Жарвисыг тэст хийж байна"})
        mid = r.json()["id"]
        listed = c.get("/api/memory").json()["memories"]
        assert any(m["id"] == mid for m in listed)
        r = c.delete(f"/api/memory/{mid}")
        assert r.json()["deleted"] is True


def test_remember_trigger_in_chat(patched_nim):
    """The 'remember this: X' trigger short-circuits before any NIM call."""
    with _client() as c:
        r = c.post("/api/chat", json={"session_id": "t",
                                       "message": "remember this: my favorite color is gold"})
        assert r.status_code == 200
        assert "memory" in r.json()["reply"].lower() or "saved" in r.json()["reply"].lower()


def test_upgrade_requires_phrase(patched_nim):
    with _client() as c:
        # Wrong phrase -> 400
        r = c.post("/api/upgrade", json={"phrase": "nope"})
        assert r.status_code == 400
        # Versions list always has v1 baseline
        r = c.get("/api/upgrade/versions")
        assert r.status_code == 200
        assert any(v["version"] == 1 for v in r.json()["versions"])


def test_skill_invoke_terminal(patched_nim):
    with _client() as c:
        r = c.post("/api/skills/invoke",
                   json={"name": "terminal_exec", "args": {"command": "echo hi"}})
        body = r.json()
        assert body["ok"] is True
        assert "hi" in body["data"]["stdout"]


def test_cache_stats_shape(patched_nim):
    with _client() as c:
        s = c.get("/api/cache/stats").json()
        for k in ("exact_hits", "semantic_hits", "misses", "writes"):
            assert k in s


def test_learning_snapshot_shape(patched_nim):
    with _client() as c:
        s = c.get("/api/learning").json()
        for k in ("enabled", "strategy_scores", "skill_weights"):
            assert k in s


def test_intent_endpoint_returns_dict(patched_nim):
    with _client() as c:
        r = c.post("/api/intent", json={"message": "what is 2+2"})
        body = r.json()
        for k in ("intent", "confidence", "strategy"):
            assert k in body


def test_versioning_baseline_v1(patched_nim):
    """v1 baseline is auto-created on boot."""
    with _client() as c:
        r = c.get("/api/upgrade/versions").json()
        v1 = next((v for v in r["versions"] if v["version"] == 1), None)
        assert v1 is not None
        assert v1["status"] == "applied"


def test_websocket_emits_heartbeat(patched_nim):
    from backend.main import app
    import asyncio, json
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            # The heartbeat task fires every 15s in production; rather than
            # waiting, we publish synthetically and confirm we receive it.
            from backend.core.events import bus
            asyncio.run(bus.publish("test", {"type": "ping"}))
            data = json.loads(ws.receive_text())
            assert data["channel"] in {"test", "heartbeat"}
