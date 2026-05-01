#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Python virtualenv"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Frontend deps"
( cd frontend && npm install )

echo "==> Data dirs"
mkdir -p data logs versions

echo "==> Done. Copy .env.example to .env and set NVIDIA_API_KEY, then run scripts/start.sh"
