"""about.py — GET /api/about: what this Pipesets server is and runs on, for the About panel. Any signed-in
user: the version and commit, Python and the backend libraries (installed versions), the database type
and version (never its host, name or credentials), the LLM gateway's backends, and how many built-in
tools, MCP servers, agents and skills it ships."""

import platform
import sys
from importlib import metadata
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request

from services import release_notes
from services.request_context import get_request_context
from version import APP_VERSION

router = APIRouter(prefix="/api/about", tags=["about"])

# (label, distribution name, what it does here)
LIBRARIES = [
    ("FastAPI", "fastapi", "HTTP API"),
    ("Uvicorn", "uvicorn", "ASGI server"),
    ("Pydantic", "pydantic", "Request and config models"),
    ("SQLAlchemy", "sqlalchemy", "Database access"),
    ("Alembic", "alembic", "Schema migrations"),
    ("HTTPX", "httpx", "Tool and model HTTP calls"),
    ("MCP SDK", "mcp", "MCP client and server"),
    ("Cryptography", "cryptography", "Secret vault encryption"),
    ("OpenTelemetry", "opentelemetry-api", "Traces and metrics export"),
    ("Docling", "docling", "Document parsing and OCR"),
    ("LiteLLM", "litellm", "Legacy model-call fallback"),
]


def _version(dist: str) -> Optional[str]:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def _database() -> Dict[str, Any]:
    try:
        from db import get_engine
        engine = get_engine()
        with engine.connect():
            info = engine.dialect.server_version_info
        return {"type": engine.dialect.name, "driver": engine.dialect.driver,
                "version": ".".join(str(v) for v in info) if info else ""}
    except Exception:   # the page must load even when the database is down
        return {"type": "unknown", "driver": "", "version": ""}


def _catalog() -> Dict[str, int]:
    import agents
    import tools
    from routers.skills import BUILTIN_SKILLS

    tools._load()
    sections = {s["id"]: len(s["tools"]) for s in tools.catalog()}
    specs = agents.all_specs()
    return {"tools": sections.get("agentic_tools", 0), "mcp_servers": sections.get("mcp_servers", 0),
            "frameworks": sections.get("frameworks", 0), "agents": sum(1 for s in specs if not s.starter),
            "starter_roles": sum(1 for s in specs if s.starter), "skills": len(BUILTIN_SKILLS)}


def _llm_backends() -> list:
    try:
        from llm.backends import BACKENDS
        return sorted(getattr(b, "id", str(b)) for b in (BACKENDS.values() if isinstance(BACKENDS, dict) else BACKENDS))
    except Exception:
        return []


@router.get("")
def get_about(request: Request) -> Dict[str, Any]:
    get_request_context(request)   # signed in
    latest = release_notes.latest(1)
    commit = latest["commits"][0] if latest["commits"] else None
    return {
        "app": {"name": "Pipesets AI", "version": APP_VERSION, "license": "Apache-2.0",
                "commit": {k: commit[k] for k in ("short", "hash", "date", "subject")} if commit else None},
        "backend": {
            "python": platform.python_version(), "implementation": platform.python_implementation(),
            "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "frozen": bool(getattr(sys, "frozen", False)),
            "libraries": [{"name": n, "version": v, "role": r} for n, d, r in LIBRARIES if (v := _version(d))],
            "database": _database(),
            "llm_backends": _llm_backends(),
        },
        "catalog": _catalog(),
    }
