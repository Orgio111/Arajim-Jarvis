#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Detect a Python interpreter compatible with the pinned dependencies.
# Several packages in requirements.txt (pydantic-core for pydantic 2.9.2,
# tiktoken 0.8.0, av via faster-whisper 1.0.3) only ship prebuilt wheels up to
# Python 3.12 / 3.13. On Python 3.14 pip falls back to source builds that need
# FFmpeg dev headers and a C toolchain, which is rarely what the user wants.
# We therefore prefer 3.12, then 3.11, then 3.13, before falling back to whatever
# Python 3 is on PATH.
PREFERRED_PYTHON_VERSIONS=(3.12 3.11 3.13)

is_python3() {
  "$@" -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" >/dev/null 2>&1
}

find_python() {
  # Windows Python launcher with explicit version is the most reliable on
  # Git Bash / MSYS.
  if command -v py >/dev/null 2>&1; then
    for v in "${PREFERRED_PYTHON_VERSIONS[@]}"; do
      if py "-${v}" --version >/dev/null 2>&1; then
        echo "py -${v}"
        return 0
      fi
    done
    if py -3 --version >/dev/null 2>&1; then
      echo "py -3"
      return 0
    fi
  fi

  # Try versioned binaries on PATH (python3.12, python3.11, ...).
  for v in "${PREFERRED_PYTHON_VERSIONS[@]}"; do
    if command -v "python${v}" >/dev/null 2>&1; then
      echo "python${v}"
      return 0
    fi
  done

  # Fall back to generic python3 / python, skipping the WindowsApps Microsoft
  # Store stubs that hijack the name.
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      local resolved
      resolved="$(command -v "$candidate")"
      case "$resolved" in
        */WindowsApps/*) continue ;;
      esac
      if is_python3 "$candidate"; then
        echo "$candidate"
        return 0
      fi
    fi
  done

  return 1
}

PYTHON_CMD="$(find_python || true)"
if [ -z "${PYTHON_CMD}" ]; then
  echo "ERROR: Python 3 not found." >&2
  echo "Install Python 3.11+ from https://www.python.org/downloads/ and re-run." >&2
  echo "On Windows also disable the Microsoft Store python alias:" >&2
  echo "  Settings > Apps > Advanced app settings > App execution aliases > turn off python.exe / python3.exe" >&2
  exit 1
fi

PYTHON_VERSION="$(${PYTHON_CMD} -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
echo "==> Using Python: ${PYTHON_CMD} (Python ${PYTHON_VERSION})"

# Recreate the virtualenv if it was built against a different Python version.
if [ -d .venv ]; then
  if [ -x ".venv/Scripts/python.exe" ]; then
    EXISTING_VENV_PY=".venv/Scripts/python.exe"
  elif [ -x ".venv/bin/python" ]; then
    EXISTING_VENV_PY=".venv/bin/python"
  else
    EXISTING_VENV_PY=""
  fi
  if [ -n "${EXISTING_VENV_PY}" ]; then
    EXISTING_VENV_VERSION="$("${EXISTING_VENV_PY}" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo unknown)"
    if [ "${EXISTING_VENV_VERSION}" != "${PYTHON_VERSION}" ]; then
      echo "==> Removing stale .venv (Python ${EXISTING_VENV_VERSION} != ${PYTHON_VERSION})"
      rm -rf .venv
    fi
  fi
fi

echo "==> Python virtualenv"
${PYTHON_CMD} -m venv .venv

# venv layout differs between Windows (Scripts/) and POSIX (bin/).
if [ -f ".venv/Scripts/activate" ]; then
  VENV_ACTIVATE=".venv/Scripts/activate"
  VENV_PY=".venv/Scripts/python.exe"
elif [ -f ".venv/bin/activate" ]; then
  VENV_ACTIVATE=".venv/bin/activate"
  VENV_PY=".venv/bin/python"
else
  echo "ERROR: virtualenv was created but no activate script was found." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${VENV_ACTIVATE}"

"${VENV_PY}" -m pip install --upgrade pip
"${VENV_PY}" -m pip install -r requirements.txt

echo "==> Frontend deps"
( cd frontend && npm install )

echo "==> Data dirs"
mkdir -p data logs versions

echo "==> Done. Copy .env.example to .env and set NVIDIA_API_KEY, then run scripts/start.sh"
