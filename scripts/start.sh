#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env missing. Copy .env.example to .env and set NVIDIA_API_KEY."
  exit 1
fi

# venv layout differs between Windows (Scripts/) and POSIX (bin/).
if [ -f ".venv/Scripts/activate" ]; then
  VENV_ACTIVATE=".venv/Scripts/activate"
  VENV_PY=".venv/Scripts/python.exe"
elif [ -f ".venv/bin/activate" ]; then
  VENV_ACTIVATE=".venv/bin/activate"
  VENV_PY=".venv/bin/python"
else
  echo "ERROR: .venv not found. Run scripts/install.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${VENV_ACTIVATE}"

# Start backend (background)
( "${VENV_PY}" -m backend.main ) &
BACK_PID=$!
echo "Backend pid=$BACK_PID"

# Start frontend
( cd frontend && npm run dev ) &
FRONT_PID=$!
echo "Frontend pid=$FRONT_PID"

trap "kill $BACK_PID $FRONT_PID 2>/dev/null || true" EXIT INT TERM
wait
