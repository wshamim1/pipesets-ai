"""Databricks notebook status — built-in tool `databricks_notebook_status`."""

import json
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="databricks_notebook_status",
    name="Databricks Notebook Status",
    icon="📓",
    category="Data & Files",
    description="Checks whether a Databricks workspace notebook or file exists and returns its metadata and type.",
    default_config={"host": "", "token": "", "path": "/"},
    required=("host", "token"),
    order=270,
    parameters=params(
        {"path": {"type": "string", "description": "Databricks workspace path to inspect"}},
        {
            "include_object_type": {
                "type": "boolean",
                "description": "Include the object type in the output",
            }
        },
    ),
    input_param="path",
    config_args=("include_object_type",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    host = (cfg.get("host") or "").strip().rstrip("/")
    token = (cfg.get("token") or "").strip()
    path = (inp or cfg.get("path") or "").strip()

    missing = [name for name, value in {"host": host, "token": token, "path": path}.items() if not value]
    if missing:
        return f"[Databricks Notebook Status] Missing required config: {', '.join(missing)}"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{host}/api/2.0/workspace/get-status", params={"path": path}, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        return f"[Databricks Notebook Status] Error: {exc}"

    obj_type = payload.get("object_type") or "unknown"
    object_id = payload.get("object_id") or "n/a"
    path_value = payload.get("path") or path

    summary = {
        "path": path_value,
        "object_type": obj_type,
        "object_id": object_id,
        "exists": True,
    }

    return f"[Databricks Notebook Status]\n{json.dumps(summary, indent=2, sort_keys=True)}"
