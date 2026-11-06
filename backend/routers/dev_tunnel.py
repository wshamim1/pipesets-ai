"""
dev_tunnel.py — share the local dev UI through an ngrok tunnel, started from Settings → Share via ngrok.

GET  /api/dev/tunnel        — whether it's enabled, ngrok installed, and any tunnel to the UI (ours or
                              one started from a terminal), with its public URL
POST /api/dev/tunnel/start  — start ``ngrok http <FRONTEND_PORT>``, on ``{"domain": "…"}`` when given
                              (a reserved / free static domain keeps the URL the same every time)
POST /api/dev/tunnel/stop   — stop the tunnel this server started

Development only: off unless PIPESETS_DEV_TUNNEL=1 (start.sh sets it; Docker / k8s never do), and
server admins only — it puts this machine on the internet. The Vite dev server accepts ngrok hosts
and proxies the API (frontend/vite.config.ts), so the one forwarded port serves UI and API.
"""

import atexit
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.acl import require_server_admin
from services.request_context import get_request_context

router = APIRouter(prefix="/api/dev/tunnel", tags=["dev"])

_INSPECT_PORTS = range(4040, 4046)   # ngrok's local API: 4040, or the next free port for a second agent
_LOG = Path(os.getenv("PIPESETS_DATA_DIR") or Path(__file__).resolve().parents[1]) / "ngrok.log"
_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_proc: Optional[subprocess.Popen] = None
_domain: Optional[str] = None


def _enabled() -> bool:
    return os.getenv("PIPESETS_DEV_TUNNEL", "").strip() == "1"


def _port() -> str:
    return os.getenv("FRONTEND_PORT", "5173").strip()


def _ours() -> bool:
    return _proc is not None and _proc.poll() is None


def _tunnels() -> List[Dict[str, Any]]:
    """HTTPS tunnels to the UI port from any ngrok agent on this machine."""
    found = []
    for port in _INSPECT_PORTS:
        try:
            data = httpx.get(f"http://127.0.0.1:{port}/api/tunnels", timeout=0.5).json()
        except (httpx.HTTPError, ValueError):
            continue
        for t in data.get("tunnels", []):
            addr = str(t.get("config", {}).get("addr", ""))
            if t.get("public_url", "").startswith("https://") and addr.rstrip("/").endswith(f":{_port()}"):
                found.append({"public_url": t["public_url"], "inspect_port": port})
    return found


def _log_tail(lines: int = 6) -> str:
    try:
        text = _LOG.read_text(errors="replace").strip().splitlines()
    except OSError:
        return ""
    return "\n".join(text[-lines:])


def _status() -> Dict[str, Any]:
    tunnels = _tunnels()
    return {
        "enabled": _enabled(),
        "installed": shutil.which("ngrok") is not None,
        "port": _port(),
        "running": bool(tunnels) or _ours(),
        "ours": _ours(),
        "domain": _domain if _ours() else None,
        "public_url": tunnels[0]["public_url"] if tunnels else None,
        "inspect_url": f"http://127.0.0.1:{tunnels[0]['inspect_port']}" if tunnels else None,
    }


def _guard(request: Request) -> None:
    require_server_admin(get_request_context(request))
    if not _enabled():
        raise HTTPException(status_code=404, detail="Tunnels are off. Start the backend with PIPESETS_DEV_TUNNEL=1 (start.sh does).")


@router.get("")
def tunnel_status(request: Request) -> Dict[str, Any]:
    require_server_admin(get_request_context(request))
    return _status()


class StartBody(BaseModel):
    domain: Optional[str] = None


@router.post("/start")
def start_tunnel(body: StartBody, request: Request) -> Dict[str, Any]:
    global _proc, _domain
    _guard(request)
    if not shutil.which("ngrok"):
        raise HTTPException(status_code=400, detail="ngrok isn't installed on this machine (brew install ngrok).")
    if _ours() or _tunnels():
        status = _status()
        if status["ours"]:
            return status
        raise HTTPException(status_code=409, detail="An ngrok tunnel to the UI is already running (started from a "
                                                    "terminal). Stop it there first: the free plan allows one at a time.")
    domain = (body.domain or "").strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/") or None
    if domain and not _DOMAIN.match(domain):
        raise HTTPException(status_code=400, detail=f"“{body.domain}” isn't a domain name.")

    cmd = ["ngrok", "http", _port(), "--log", "stdout", "--log-format", "logfmt"]
    if domain:
        cmd.append(f"--url=https://{domain}")
    log = open(_LOG, "w")
    _proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True)
    _domain = domain
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _proc.poll() is not None:   # exited: bad token, domain not yours, another agent online, …
            detail = _log_tail() or f"ngrok exited with code {_proc.returncode}"
            _proc = None
            raise HTTPException(status_code=502, detail=f"ngrok didn't start:\n{detail}")
        if _tunnels():
            return _status()
        time.sleep(0.3)
    raise HTTPException(status_code=504, detail=f"ngrok started but hasn't reported a URL yet.\n{_log_tail()}")


@router.post("/stop")
def stop_tunnel(request: Request) -> Dict[str, Any]:
    _guard(request)
    _stop()
    return _status()


def _stop() -> None:
    global _proc, _domain
    if _ours():
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc, _domain = None, None


atexit.register(_stop)   # never leave the machine exposed after the backend stops
