"""
sandbox_runner.py — the sandbox runner service: runs Python for the backend in throwaway containers.

The backend sends code here (services/sandbox.py, backend "remote", SANDBOX_URL) instead of
needing a container engine of its own. This service runs it with its local podman exactly as the
backend's "container" backend would — no network unless asked, read-only root, dropped
capabilities, memory / CPU / pid limits, non-root user, requirements in a cached image — and
returns the exit code and output. It holds no secrets but its own token and never touches the
database.

    POST /run      {"code": str, "cfg": {...}}  → 200 {"returncode", "stdout", "stderr"}
                                                  422 {"error"} when the code couldn't run at all
    GET  /health   → 200 when a container engine is reachable, 503 otherwise

Every /run needs ``Authorization: Bearer $SANDBOX_TOKEN``; the service won't start without a
token. Only the backend should be able to reach it (compose: internal network; k8s:
NetworkPolicy). Standard library only, plus services/sandbox.py.

    SANDBOX_TOKEN=... python sandbox_runner.py        # listens on SANDBOX_RUNNER_PORT (8090)
"""

import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Tuple

from services import sandbox

log = logging.getLogger("sandbox-runner")

MAX_BODY = 2 * 1024 * 1024
# Caps on what a request may ask for, whatever the backend sends
MAX_TIMEOUT_S = 300
MAX_MEMORY_MB = 4096


def run(payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """(HTTP status, JSON body) for a /run request body."""
    code = payload.get("code")
    cfg = payload.get("cfg") or {}
    if not isinstance(code, str) or not isinstance(cfg, dict):
        return 400, {"error": "Expected {\"code\": str, \"cfg\": object}"}
    cfg = {
        **cfg,
        "backend": "container",   # never the runner's own process
        "timeout": min(MAX_TIMEOUT_S, max(1, int(cfg.get("timeout", 10)))),
        "memory_mb": min(MAX_MEMORY_MB, max(32, int(cfg.get("memory_mb", 256)))),
    }
    try:
        returncode, stdout, stderr = sandbox._execute(code, cfg, allow_remote=False)
    except sandbox.SandboxError as e:
        return 422, {"error": str(e)}
    return 200, {"returncode": returncode, "stdout": stdout, "stderr": stderr}


class Handler(BaseHTTPRequestHandler):
    token = ""

    def _reply(self, status: int, body: Dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != "/health":
            return self._reply(404, {"error": "not found"})
        engine = sandbox._container_runtime()
        self._reply(200 if engine else 503, {"engine": engine})

    def do_POST(self):
        if self.path != "/run":
            return self._reply(404, {"error": "not found"})
        auth = self.headers.get("Authorization", "")
        if not hmac.compare_digest(auth.encode(), f"Bearer {self.token}".encode()):
            return self._reply(401, {"error": "unauthorized"})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._reply(413 if length > MAX_BODY else 400, {"error": "body missing or too large"})
        try:
            payload = json.loads(self.rfile.read(length))
        except ValueError:
            return self._reply(400, {"error": "invalid JSON"})
        status, body = run(payload if isinstance(payload, dict) else {})
        self._reply(status, body)

    def log_message(self, fmt, *args):   # no request bodies in logs, just the line
        log.info("%s %s", self.address_string(), fmt % args)


def make_server(host: str, port: int, token: str) -> ThreadingHTTPServer:
    if not token:
        raise SystemExit("SANDBOX_TOKEN is required")
    handler = type("TokenHandler", (Handler,), {"token": token})
    return ThreadingHTTPServer((host, port), handler)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    server = make_server(os.environ.get("SANDBOX_RUNNER_HOST", "0.0.0.0"),
                         int(os.environ.get("SANDBOX_RUNNER_PORT", "8090")), os.environ.get("SANDBOX_TOKEN", ""))
    log.info("sandbox runner listening on %s:%s (engine: %s)", *server.server_address, sandbox._container_runtime())
    server.serve_forever()
