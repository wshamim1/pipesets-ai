#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_PID_FILE="${SCRIPT_DIR}/.frontend.pid"
BACKEND_PID_FILE="${SCRIPT_DIR}/.backend.pid"

FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

# Kill any processes still bound to the given port (fallback for orphaned children)
kill_by_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti ":${port}" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "  Killing orphaned processes on port ${port}: $pids"
    echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}

stop_process() {
  local name="$1"
  local pid_file="$2"
  local port="$3"

  if [ -f "$pid_file" ]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "Stopping $name (PID: $pid)..."
      # Kill the entire process group so child processes (e.g. Vite's Node worker) also die
      local pgid
      pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
      if [ -n "$pgid" ] && [ "$pgid" != "0" ]; then
        kill -- "-${pgid}" 2>/dev/null || kill "$pid" 2>/dev/null || true
      else
        kill "$pid" 2>/dev/null || true
      fi

      for _ in {1..10}; do
        if ! kill -0 "$pid" 2>/dev/null; then
          break
        fi
        sleep 0.5
      done

      if kill -0 "$pid" 2>/dev/null; then
        echo "Force killing $name process group..."
        if [ -n "$pgid" ] && [ "$pgid" != "0" ]; then
          kill -9 -- "-${pgid}" 2>/dev/null || true
        fi
        kill -9 "$pid" 2>/dev/null || true
      fi

      rm -f "$pid_file"
      echo "$name stopped."
    else
      echo "$name PID $pid was not running. Removed stale PID file."
      rm -f "$pid_file"
    fi
  else
    echo "No PID file found for $name."
  fi

  # Always sweep the port to catch any orphaned children
  kill_by_port "$port"
}

echo "Stopping Pipesets AI services..."
stop_process "Frontend" "$FRONTEND_PID_FILE" "$FRONTEND_PORT"
stop_process "Backend"  "$BACKEND_PID_FILE"  "$BACKEND_PORT"
echo "All services stopped."
