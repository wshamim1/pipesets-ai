#!/usr/bin/env bash
#
# Start the Pipesets desktop app (desktop/, Tauri) from this repo.
#
#   ./start-desktop.sh              backend runs from backend/.venv (default)
#   ./start-desktop.sh --packaged   backend runs as the PyInstaller build (built if missing)
#   ./start-desktop.sh --rebuild    with --packaged: rebuild the backend first (~2 min)
#   ./start-desktop.sh --force      start even if the web backend (start.sh) is running
#
# Runs in the foreground: closing this terminal or pressing Ctrl+C quits the app and its
# backend. Data lives in ~/Library/Application Support/ai.pipesets.desktop/, the backend
# log in ~/Library/Logs/ai.pipesets.desktop/backend.log (see desktop/README.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="${SCRIPT_DIR}/desktop"
BACKEND_DIR="${SCRIPT_DIR}/backend"
BACKEND_PID_FILE="${SCRIPT_DIR}/.backend.pid"
PACKAGED_BIN="${BACKEND_DIR}/dist/pipesets-backend/pipesets-backend"

PACKAGED=0
REBUILD=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --packaged) PACKAGED=1 ;;
    --rebuild)  REBUILD=1 ;;
    --force)    FORCE=1 ;;
    -h|--help)  sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (see --help)"; exit 1 ;;
  esac
done

# 1. Rust toolchain (rustup puts it in ~/.cargo; terminals opened before installing it lack the PATH)
if ! command -v cargo >/dev/null 2>&1 && [ -f "$HOME/.cargo/env" ]; then
  # shellcheck disable=SC1091
  . "$HOME/.cargo/env"
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo "Rust is not installed. Install it with:"
  echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  exit 1
fi

# 2. The web backend and the desktop app hold copies of the same schedules — both would fire them
if [ "$FORCE" -eq 0 ] && [ -f "$BACKEND_PID_FILE" ] && kill -0 "$(cat "$BACKEND_PID_FILE")" 2>/dev/null; then
  echo "The web backend is running (PID: $(cat "$BACKEND_PID_FILE"))."
  echo "Running both fires every scheduled pipeline twice."
  answer=""
  if [ -t 0 ]; then
    read -r -p "Stop the web app (./stop.sh) and continue? [Y/n] " answer
  fi
  if [ -t 0 ] && [[ ! "$answer" =~ ^[Nn] ]]; then
    "${SCRIPT_DIR}/stop.sh"
  else
    echo "Stop it with ./stop.sh, or start anyway with: ./start-desktop.sh --force"
    exit 1
  fi
fi

# 3. Backend: the venv (default) or the packaged build
if [ "$PACKAGED" -eq 1 ]; then
  if [ "$REBUILD" -eq 1 ] || [ ! -x "$PACKAGED_BIN" ]; then
    echo "Building the packaged backend (about 2 minutes)..."
    if ! "${BACKEND_DIR}/.venv/bin/python" -c "import PyInstaller" 2>/dev/null; then
      "${BACKEND_DIR}/.venv/bin/python" -m pip install -r "${BACKEND_DIR}/requirements-build.txt"
    fi
    (cd "$BACKEND_DIR" && .venv/bin/python -m PyInstaller pipesets-backend.spec --noconfirm)
  fi
elif [ ! -x "${BACKEND_DIR}/.venv/bin/python" ]; then
  echo "backend/.venv is missing. Run ./start.sh once to set it up (then ./stop.sh)."
  exit 1
fi

# 4. Desktop dependencies
cd "$DESKTOP_DIR"
if [ ! -d node_modules ]; then
  echo "Installing desktop dependencies..."
  npm install
fi

echo ""
echo "=================================================="
echo "Starting Pipesets desktop ($([ "$PACKAGED" -eq 1 ] && echo "packaged backend" || echo "backend from backend/.venv"))"
echo "Data: ~/Library/Application Support/ai.pipesets.desktop/"
echo "Log:  ~/Library/Logs/ai.pipesets.desktop/backend.log"
echo "Quit the app or press Ctrl+C to stop."
echo "=================================================="

if [ "$PACKAGED" -eq 1 ]; then
  exec npm run dev:packaged
fi
exec npm run dev
