# ARAJIM-JARVIS

A production-grade, NVIDIA NIM-powered autonomous AI operating system. JARVIS-level intelligence with multi-agent collaboration, persistent memory, voice control (Mongolian + English), continuous execution, full system access, and a controlled self-upgrade mechanism.

## What It Is

Arajim-Jarvis is a continuously running AI environment that:

- **Thinks** — multi-agent reasoning across Planner / Executor / Coder / Reviewer / Optimizer
- **Acts** — executes terminal commands, controls files, runs apps, performs real OS-level work
- **Learns** — persistent memory, chat history, skill registry that grows over time
- **Upgrades itself** — only when the user explicitly says `upgrade myself` (versioned, reversible)
- **Speaks** — voice activation, Mongolian + English STT/TTS

NVIDIA NIM is the **only** LLM backend. Every model call routes through the dynamic NIM router which picks the best model per task (reasoning, coding, fast classification).

## Quick Start

```bash
# 1. Set your NVIDIA NIM key
cp .env.example .env
# edit .env and set NVIDIA_API_KEY=nvapi-...

# 2. Install
./scripts/install.sh

# 3. Run
./scripts/start.sh
```

Open http://localhost:5173 for the dashboard. Backend runs on http://localhost:8000.

See `docs/SETUP.md` for full setup, `docs/ARCHITECTURE.md` for design, and `docs/UPGRADE_SYSTEM.md` for the self-improvement mechanism.

## Modes

- **Full Auto** — JARVIS plans and executes without confirmation
- **Smart Assist** — confirms only critical actions
- **Manual** — every action requires user approval

## Core Commands

- `remember this: <fact>` — store in persistent memory
- `forget <id>` — remove a memory entry
- `upgrade myself` — trigger versioned self-improvement (only the user can do this)
- `jarvis on` / `jarvis off` — toggle voice mode

## License

Proprietary — Arajim.
