# Setup Guide

## Prerequisites

- Python 3.11+
- Node 18+
- An NVIDIA NIM API key from <https://build.nvidia.com/settings/api-keys> (free tier is fine to start)
- Optional: Docker for self-hosted NIM containers

## Install

```bash
git clone <this-repo> arajim-jarvis
cd arajim-jarvis
cp .env.example .env
# Edit .env and set NVIDIA_API_KEY=nvapi-...
./scripts/install.sh
```

`install.sh` creates a Python venv, installs deps, runs `npm install` for the frontend, and creates `data/`, `logs/`, `versions/`.

## Run

```bash
./scripts/start.sh
```

- Backend: <http://localhost:8000> (Swagger at `/docs`)
- Frontend: <http://localhost:5173>
- WebSocket: `ws://localhost:8000/ws`

## Self-hosted NIM (optional)

If you run an NVIDIA NIM container locally (e.g. `nemotron-super-49b`), point `NVIDIA_BASE_URL` at it — the OpenAI-compatible schema is identical:

```env
NVIDIA_BASE_URL=http://localhost:8000/v1
```

Run the FastAPI app on a different port (`BACKEND_PORT=8080`) so you don't collide.

## First requests

```
You: hello
JARVIS: ...

You: list files in /tmp
JARVIS: <streams ls output>

You: remember this: my name is Arajim
JARVIS: Saved as memory #1: my name is Arajim

You: what's my name?
JARVIS: Arajim — I just remembered.

You: upgrade myself
JARVIS: <runs the controlled upgrade pipeline; new v2 created>
```

## Modes

Set in `.env` or change live in the UI top-left:

- `full_auto` — runs everything without prompts
- `smart_assist` — prompts only on dangerous commands (rm, sudo, dd, format, mkfs, shutdown, reboot)
- `manual` — every action waits for click-approval

## Voice (optional)

Voice uses `faster-whisper` and `edge-tts`. First STT call downloads the model (~150 MB for `small`). Mongolian is supported out of the box (`VOICE_LANG=mn`).

```bash
# pre-download model (optional)
python -c "from faster_whisper import WhisperModel; WhisperModel('small')"
```

Click the 🎙 button on the topbar to toggle. Voice transcription happens server-side; the browser captures audio via MediaRecorder and POSTs to `/api/voice/transcribe`.

## Production

```bash
# Build frontend static
cd frontend && npm run build

# Run backend with multiple workers
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Use 1 worker — the event bus and permission queue are in-process. For HA, put a queue (Redis) behind the bus and run multiple workers behind a sticky-session proxy.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `NIM chat failed: 401` | NVIDIA_API_KEY missing or wrong. Check `.env`. |
| `NIM chat failed: 429` | Free tier rate limit (~40 RPM). Router auto-backs off; reduce parallelism. |
| Memory not persisting | Check `MEMORY_DB_PATH` is writable. Default `./data/memory.db`. |
| Upgrade rolled back | A patch failed validation. See `versions/v<N>/manifest.json` `notes`. |
| Voice transcribe slow | Pre-download Whisper model; or set `model_size=tiny` in `voice/stt.py`. |
