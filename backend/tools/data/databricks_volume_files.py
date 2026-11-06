"""Databricks volume files — built-in tool `databricks_volume_files`: lists a Unity Catalog volume
directory, or reads a file in one, through the Files API."""

import json
from typing import Any, Dict, Optional
from urllib.parse import quote

from tools.base import ToolSpec, params
from tools.data._databricks import credentials, missing, report, request

LABEL = "Databricks Volume Files"

TOOL = ToolSpec(
    id="databricks_volume_files",
    name=LABEL,
    icon="📁",
    category="Data & Files",
    description="Lists a Unity Catalog volume directory or reads a text file from it (paths like /Volumes/catalog/schema/volume/...).",
    default_config={"host": "", "token": "", "path": "", "max_chars": 20000},
    required=("host", "token"),
    order=345,
    parameters=params(
        {"path": {"type": "string", "description": "Volume path, e.g. /Volumes/main/default/raw/data.csv"}},
        {"max_chars": {"type": "integer", "minimum": 100, "maximum": 200000,
                       "description": "Maximum characters of file content to return"}},
    ),
    input_param="path",
    config_args=("max_chars",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    path = (inp or cfg.get("path") or "").strip()
    host, token = credentials(cfg)
    problem = missing(LABEL, host=host, token=token, path=path)
    if problem:
        return problem
    if not path.startswith("/Volumes/"):
        return f"[{LABEL}] Path must start with /Volumes/ (got '{path}')"
    encoded = quote(path.rstrip("/") or "/")

    listing, error = await request(LABEL, cfg, "GET", f"/api/2.0/fs/directories{encoded}")
    if not error:
        entries = [{"name": e.get("name"), "path": e.get("path"), "is_directory": e.get("is_directory"),
                    "size": e.get("file_size")} for e in (listing or {}).get("contents") or []]
        return report(LABEL, {"path": path, "type": "directory", "entries": entries})
    if "HTTP 404" not in error and "HTTP 400" not in error:
        return error

    content, error = await request(LABEL, cfg, "GET", f"/api/2.0/fs/files{encoded}", timeout=60.0)
    if error:
        return error
    text = content if isinstance(content, str) else json.dumps(content, indent=2)
    max_chars = int(cfg.get("max_chars") or 20000)
    suffix = f"\n… truncated at {max_chars} of {len(text)} characters" if len(text) > max_chars else ""
    return f"[{LABEL}] {path}\n{text[:max_chars]}{suffix}"
