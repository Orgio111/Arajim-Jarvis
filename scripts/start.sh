#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env missing. Copy .env.example to .env and set NVIDIA_API_KEY."
  exit 1
fi

source .venv/bin/activate

# Start backend (background)
( python -m backend.main ) &
BACK_PID=$!
echo "Backend pid=$BACK_PID"

# Start frontend
( cd frontend && npm run dev ) &
FRONT_PID=$!
echo "Frontend pid=$FRONT_PID"

trap "kill $BACK_PID $FRONT_PID 2>/dev/null || true" EXIT INT TERM
wait
