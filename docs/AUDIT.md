# System Audit & Hardening (post-v2)

A self-audit was performed against the original brief plus the v2 extension brief. This document records what was found, what was fixed in the hardening pass, and what is intentionally deferred.

## Scorecard vs. requirements

| Requirement | Status | Notes |
|---|---|---|
| NVIDIA NIM as the only LLM transport | ✅ | `backend/nvidia/client.py` is the single transport. No other LLM SDK imported anywhere. |
| Multi-agent (Planner/Executor/Coder/Reviewer/Optimizer) | ✅ | Each role pulls a tier-appropriate model from the router. |
| Modes (full_auto / smart_assist / manual) | ✅ | Enforced at `backend/system/permissions.py`. |
| Persistent + chat memory with `remember this` / `forget` | ✅ | SQLite via aiosqlite, Cyrillic-safe. |
| Voice (Mongolian + English) STT + TTS | ✅ | faster-whisper + edge-tts; `mn-MN-BataaNeural`, `en-US-GuyNeural`. |
| Browser mic capture + audio playback | ✅ (v3) | `frontend/src/voice.js` MediaRecorder + `/api/voice/converse` returns audio. |
| Skill system (modular, auto-select) | ✅ | 12 built-in skills, NIM-classified router. |
| Futuristic dashboard, real-time logs | ✅ | React + Vite + WebSocket event bus. |
| Continuous execution / auto-recovery | ✅ (v3) | Orchestrator wraps `handle()` in a watchdog that converts crashes into chat replies + bus events. |
| Self-upgrade with versioning | ✅ | User-only `upgrade myself` trigger; snapshot/manifest/changelog/rollback; protected files. |
| Full system access (terminal, fs, admin) | ✅ | Streamed terminal exec, fs ops, optional firejail sandbox. |
| Permission control layer | ✅ | Per-mode gating with UI confirmation cards. |
| Optional auth on /api | ✅ (v3) | `JARVIS_AUTH_TOKEN` enables bearer-token guard; loopback exempt unless strict. |
| Streaming responses (token-by-token) | ✅ | `/api/chat/stream` SSE; frontend renders deltas live. |
| Two-tier cache (exact + semantic) | ✅ | In-memory or Redis backend; cache invalidates on memory mutations (v3 fix). |
| Vector memory + auto-link | ✅ | numpy or FAISS; `find_related` runs on every insert. |
| Auto-summarization of old chat | ✅ | `summarize_old_turns()` runs when history > `SUMMARIZE_AFTER`. |
| Internet search | ✅ | DuckDuckGo (no key), Tavily, Serper. |
| Deep search (multi-step reasoning) | ✅ | `search → analyze → refine → synthesize` with citations. |
| Auto-learning (passive) | ✅ | Telemetry → router scores + skill weights, persisted. |
| Active upgrade only via "upgrade myself" | ✅ | Strict trigger check; cannot self-trigger. |
| Intent prediction / dynamic strategy | ✅ | Fast NIM classifier + passive-learner override. |
| Agent debate / cross-review | ✅ | `backend/agents/collaboration.py` debate loop, `cross_review` parallel. |
| Memory auto-link + proactive surfacing | ✅ | Vector store on insert; semantic context injection on every prompt. |
| NVIDIA model intelligence (auto-discover) | ✅ | `discover_and_register()` merges `/v1/models` at boot. |
| Parallel model execution + best-result merging | ✅ (v3) | `POST /api/models/race` (fastest wins), `POST /api/models/merge_best` (reviewer judges). |
| Native NIM tool calling | ✅ (v3) | Executor falls back to OpenAI-compatible `tools=` + `tool_choice="auto"`. |
| Tests | ✅ (v3) | `tests/test_smoke.py` — 13 tests cover boot, skills, memory, modes, upgrade, cache, learning, intent, websocket. |
| Containerization | ✅ (v3) | `Dockerfile` (backend + frontend stages) + `docker-compose.yml` with Redis. |

## Issues fixed in this hardening pass (v3)

1. **Voice/speak endpoint returned only a byte count** → now returns the full audio as `audio/mpeg`.
2. **No browser mic capture** → `frontend/src/voice.js` (`VoiceController`) uses MediaRecorder and plays the JARVIS reply audio back. Toggle button drives it.
3. **No /api/voice/converse end-to-end loop** → added; mic blob in, JARVIS audio out, transcript and reply text in response headers.
4. **Native NIM function calling unused** → Executor's third fallback now sends `tools=registry.tool_schemas()` and parses `message.tool_calls`.
5. **`NIM_PARALLEL_RACE` config flag was dead** → exposed via `POST /api/models/race` and `POST /api/models/merge_best` endpoints; debate already covered the multi-agent path.
6. **No watchdog at orchestrator entry** → top-level `handle()` wraps `_handle_inner` in try/except that publishes to the `error` channel and replies with a recovery message instead of crashing.
7. **Cache could return stale replies after memory changes** → `cache.invalidate(CACHE_NS)` runs after every `remember this` / `forget` trigger.
8. **No auth layer** → `backend/auth.py` adds an optional bearer-token guard (`JARVIS_AUTH_TOKEN`); applied as a router-level dependency.
9. **No tests** → 13 pytest smoke tests covering health, skills, modes, memory, upgrade, cache, learning, intent, websocket. Run: `pytest tests/`.
10. **No container build** → multi-stage Dockerfile + compose with Redis.

## Known limitations (intentional)

- **Embeddings fallback**: when NIM `/v1/embeddings` is unreachable, the embedder degrades to a hash-based pseudo-vector (`backend/nvidia/embeddings.py:_hash_embeddings`). This keeps the system running but semantic cache hit-rate drops to near zero — acceptable degradation.
- **DuckDuckGo HTML scrape** is brittle by nature; for production set `SEARCH_BACKEND=tavily` and provide `TAVILY_API_KEY`.
- **Sandbox isolation** uses firejail when present, otherwise just constrains CWD. Real isolation in untrusted environments needs Docker/gVisor — out of scope here.
- **Auth scope**: bearer-token guard is project-internal; for multi-user deployment add OIDC / session-cookie middleware in front.
- **Single-worker assumption**: in-process event bus + permission queue mean uvicorn must run with `--workers 1` (or stick a Redis pub/sub behind the bus). See `docs/SETUP.md` "Production".

## How to verify

```bash
# Unit tests (no NIM key needed; mocks stub the client)
pytest tests/

# Live API health
curl -s http://localhost:8000/api/health | jq .

# Skills inventory
curl -s http://localhost:8000/api/skills | jq '.skills[].name'

# Memory triggers (no NIM call)
curl -s -X POST http://localhost:8000/api/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"t","message":"remember this: гэртээ хооллоход дуртай"}' | jq .

# NVIDIA model race
curl -s -X POST http://localhost:8000/api/models/race -H 'Content-Type: application/json' \
  -d '{"prompt":"What is 2+2?"}' | jq .

# Best-result merge
curl -s -X POST http://localhost:8000/api/models/merge_best -H 'Content-Type: application/json' \
  -d '{"prompt":"Write a one-sentence haiku."}' | jq .

# Streaming chat
curl -N -X POST http://localhost:8000/api/chat/stream -H 'Content-Type: application/json' \
  -d '{"session_id":"t","message":"hello"}'
```
