# Architecture

```
┌────────────────────────────────────── React Dashboard ────────────────────────────────────┐
│  Topbar (status / mode / upgrade)   Chat   Agents   Memory   Versions   Live Stream      │
└─────────────────────────────────────────────────────┬─────────────────────────────────────┘
                                                       │ HTTP + WebSocket
┌──────────────────────────────────────────────────────▼────────────────────────────────────┐
│                                       FastAPI (backend/main.py)                           │
│                                                                                           │
│   /api/chat ─────────► Orchestrator ──► Planner ──► [Executor | Coder | Reviewer | …]    │
│   /api/upgrade ──────► UpgradeManager ──► snapshot ──► propose ──► rewrite ──► review     │
│   /api/permissions ──► PermissionManager (mode-aware gating)                              │
│   /api/voice ────────► VoicePipeline (faster-whisper + edge-tts, Mongolian + English)     │
│   /ws ───────────────► EventBus pub/sub stream                                            │
│                                                                                           │
│           ┌────────────────────── NVIDIA NIM (the only LLM transport) ──────────────────┐ │
│           │  AsyncOpenAI(base_url=integrate.api.nvidia.com/v1)                          │ │
│           │  ModelRouter ──► picks per tier:                                            │ │
│           │     reasoning  → llama-3.3-nemotron-ultra-253b                              │ │
│           │     general    → llama-3.3-nemotron-super-49b                               │ │
│           │     code       → deepseek-v4-flash                                          │ │
│           │     fast       → llama-3.3-nemotron-nano-8b                                 │ │
│           │     long_ctx   → moonshotai/kimi-k2.5                                       │ │
│           └─────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                           │
│   Skills registry ──► system / code / web / file / memory                                │
│   Memory store (SQLite, aiosqlite): persistent facts + chat history                       │
│   System control: terminal (streamed), filesystem, sandbox wrapper                        │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

## Why NVIDIA NIM only

The brief calls for NVIDIA-first; we deliberately do not import any other LLM SDK. NIM is OpenAI-compatible so the official `openai` SDK works directly against `integrate.api.nvidia.com/v1`. Every model call passes through `backend/nvidia/client.py`. The `ModelRouter` picks the best model per task (reasoning / general / code / fast / long context) using a curated catalog merged with live `/v1/models` discovery and runtime telemetry.

## Multi-agent flow

`Orchestrator` (`backend/agents/orchestrator.py`) implements the loop:

1. Memory triggers (`remember this` / `forget N`) handled inline.
2. **Planner** (Nemotron-Ultra reasoning) emits a JSON plan of steps.
3. Steps without dependencies run in parallel via `asyncio.gather`.
4. Each step runs on its agent (executor / coder / reviewer / optimizer).
5. Results synthesized into one user-facing reply.
6. Everything emits to the event bus, streamed live to the UI.

## Self-upgrade

User-only trigger: typing `upgrade myself` in chat or clicking the topbar button. Pipeline:

1. Snapshot `backend/` to `versions/v<N>/snapshot/`.
2. Reasoning model proposes 1–3 patches (`Architect` system prompt).
3. Coder model rewrites each target file (full-file rewrite).
4. Reviewer model + Python syntax compile validate the rewrite.
5. Approved patches applied, smoke test reloads modules.
6. On failure: automatic rollback to current version.

Files in `PROTECTED` (manager itself, versioning, config, main) cannot be touched. Rollback restores any version's snapshot over `backend/`.

## Modes

| Mode | Behavior |
|------|---------|
| **full_auto**     | No confirmation prompts. JARVIS executes everything. |
| **smart_assist**  | Confirms only commands matching `REQUIRE_CONFIRM_FOR` keywords or risky paths. |
| **manual**        | Every action waits for user approval in the UI. |

`PermissionManager` returns a `Future` that the UI resolves via `/api/permissions/<id>/approve` or `/deny`.

## Voice

- STT: `faster-whisper small` (multilingual, includes Mongolian).
- TTS: `edge-tts` with `mn-MN-BataaNeural` for Mongolian, `en-US-GuyNeural` for English.
- Pipeline: audio → STT → orchestrator → reply → TTS audio.

## Event bus

`backend/core/events.py` provides an in-process pub/sub. Channels include `chat`, `agent`, `step`, `terminal`, `fs`, `voice`, `upgrade`, `action`, `heartbeat`. The WebSocket endpoint subscribes to `*` and forwards everything to the UI for the live stream view.

## Continuous execution

`backend/main.py` schedules a `_heartbeat` task that publishes a tick every 15s. Combined with FastAPI's lifespan + uvicorn's `--reload=False` (production), the system runs indefinitely. Auto-recovery: dangerous command failures don't crash the orchestrator (they're returned as step failures); upgrade failures auto-rollback.
