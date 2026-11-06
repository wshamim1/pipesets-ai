"""Databricks workspace files — built-in tool `databricks_workspace_files`."""

import json
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="databricks_workspace_files",
    name="Databricks Workspace Files",
    icon="📁",
    category="Data & Files",
    description="Lists files and folders under a Databricks workspace path, useful for notebook and repo inspection.",
    default_config={"host": "", "token": "", "path": "/"},
    required=("host", "token"),
    order=250,
    parameters=params(
        {"path": {"type": "string", "description": "Workspace path to list, such as /Users/me or /Workspace/Shared"}},
        {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
                "description": "Maximum number of entries to return",
            }
        },
    ),
    input_param="path",
    config_args=("limit",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    host = (cfg.get("host") or "").strip().rstrip("/")
    token = (cfg.get("token") or "").strip()
    path = (inp or cfg.get("path") or "").strip()

    missing = [name for name, value in {"host": host, "token": token, "path": path}.items() if not value]
    if missing:
        return f"[Databricks Workspace Files] Missing required config: {', '.join(missing)}"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"path": path, "format": "json"}
    limit = int(cfg.get("limit") or 50)
    if limit:
        params["page_size"] = min(limit, 200)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{host}/api/2.0/workspace/list", params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        return f"[Databricks Workspace Files] Error: {exc}"

    entries = payload.get("objects") or []
    if not entries:
        return f"[Databricks Workspace Files] No entries found at {path}."

    lines = [f"Path: {path}"]
    for entry in entries[:limit]:
        object_type = entry.get("object_type") or "unknown"
        path_value = entry.get("path") or ""
        lines.append(f"- {object_type}: {path_value}")
    return "\n".join(lines)
