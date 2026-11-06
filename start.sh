#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_PID_FILE="${SCRIPT_DIR}/.frontend.pid"
BACKEND_PID_FILE="${SCRIPT_DIR}/.backend.pid"

FRONTEND_LOG="${SCRIPT_DIR}/frontend.log"
BACKEND_LOG="${SCRIPT_DIR}/backend.log"
BACKEND_REQ_HASH_FILE="${SCRIPT_DIR}/.backend_requirements.sha256"

FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

# 1. Start Backend (FastAPI / Uvicorn)
if [ -f "$BACKEND_PID_FILE" ] && kill -0 "$(cat "$BACKEND_PID_FILE")" 2>/dev/null; then
  echo "Backend is already running (PID: $(cat "$BACKEND_PID_FILE"), http://localhost:${BACKEND_PORT})"
else
  echo "Starting Backend API on port ${BACKEND_PORT}..."
  cd "${SCRIPT_DIR}/backend"

  # Setup venv if not already set up
  if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment for backend..."
    python3 -m venv .venv
  fi

  # Use the venv's interpreter by path rather than `activate` + bare pip/uvicorn: a venv
  # copied from another folder keeps an activate script and script shebangs that point
  # at the old location, which silently runs (and installs into) the wrong environment.
  PY="${SCRIPT_DIR}/backend/.venv/bin/python"
  # Hash covers the venv too, so switching/recreating it triggers a fresh install
  REQ_HASH="$( (cat requirements.txt; "$PY" -c 'import sys; print(sys.prefix)') | shasum -a 256 | awk '{print $1}')"
  PREV_REQ_HASH=""
  if [ -f "$BACKEND_REQ_HASH_FILE" ]; then
    PREV_REQ_HASH="$(cat "$BACKEND_REQ_HASH_FILE")"
  fi

  if [ "$REQ_HASH" != "$PREV_REQ_HASH" ]; then
    echo "Installing/updating backend dependencies (requirements changed)..."
    "$PY" -m pip install -r requirements.txt
    echo "$REQ_HASH" > "$BACKEND_REQ_HASH_FILE"
  else
    echo "Backend dependencies unchanged; skipping pip install."
  fi

  # PIPESETS_DEV_TUNNEL: Settings → Share via ngrok may start a tunnel to the UI (dev only; set it to 0 to turn off)
  # TOOLS_AUTO_RELOAD: new or edited modules in backend/tools/ are picked up without a restart (dev only; 0 turns it off)
  PIPESETS_DEV_TUNNEL="${PIPESETS_DEV_TUNNEL:-1}" FRONTEND_PORT="${FRONTEND_PORT}" \
    TOOLS_AUTO_RELOAD="${TOOLS_AUTO_RELOAD:-1}" \
    nohup "$PY" -m uvicorn main:app --host 0.0.0.0 --port "${BACKEND_PORT}" > "$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!
  echo "$BACKEND_PID" > "$BACKEND_PID_FILE"
  echo "Backend started (PID: $BACKEND_PID, http://localhost:${BACKEND_PORT})"
fi

# 2. Start Frontend (Vite)
if [ -f "$FRONTEND_PID_FILE" ] && kill -0 "$(cat "$FRONTEND_PID_FILE")" 2>/dev/null; then
  echo "Frontend is already running (PID: $(cat "$FRONTEND_PID_FILE"), http://localhost:${FRONTEND_PORT})"
else
  echo "Starting Frontend UI on port ${FRONTEND_PORT}..."
  cd "${SCRIPT_DIR}/frontend"

  if [ ! -d "node_modules" ]; then
    echo "Installing frontend npm dependencies..."
    npm install
  fi

  nohup npx vite --port "${FRONTEND_PORT}" > "$FRONTEND_LOG" 2>&1 &
  FRONTEND_PID=$!
  echo "$FRONTEND_PID" > "$FRONTEND_PID_FILE"
  echo "Frontend started (PID: $FRONTEND_PID, http://localhost:${FRONTEND_PORT})"
fi

echo ""
echo "=================================================="
echo "Pipesets AI is RUNNING"
echo "Frontend: http://localhost:${FRONTEND_PORT}"
echo "Backend:  http://localhost:${BACKEND_PORT} (Docs: http://localhost:${BACKEND_PORT}/docs)"
echo "Logs:     ${FRONTEND_LOG} | ${BACKEND_LOG}"
echo "=================================================="
