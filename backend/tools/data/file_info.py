"""File Info — built-in tool `file_info`."""

import os
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params, tool_path

TOOL = ToolSpec(
    id="file_info",
    name="File Info",
    icon="🔍",
    category="Data & Files",
    description="Shows a local file's details: size, type (by extension), created/modified times and line count. Input is the file path.",
    default_config={"allowed_dir": ""},
    order=160,
    parameters=params({"path": {"type": "string", "description": "File path"}}),
    input_param="path",
)


def _line_count(path: str) -> Optional[int]:
    """Text lines for a file, or None if it can't be read as text."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(16 * 1024 * 1024)  # 16 MB is plenty for a line count
        if not data:
            return 0
        return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)
    except OSError:
        return None


def _inspect(path: str) -> Dict[str, Any]:
    st = os.stat(path)
    is_dir = os.path.isdir(path)
    return {"size": st.st_size, "created": st.st_ctime, "modified": st.st_mtime, "dir": is_dir,
            "ext": os.path.splitext(path)[1].lower(), "lines": None if is_dir else _line_count(path)}


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import asyncio
    from datetime import datetime

    path, error = tool_path(inp, cfg, "File Info")
    if error:
        return error
    try:
        info = await asyncio.to_thread(_inspect, path)
    except FileNotFoundError:
        return f"[File Info] Not found: {path}"
    except Exception as e:
        return f"[File Info] Error: {e}"

    def when(ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    def human(n: int) -> str:
        return f"{n/1024/1024:.1f} MB" if n >= 1024 * 1024 else f"{n/1024:.1f} KB" if n >= 1024 else f"{n} B"

    kind = "directory" if info["dir"] else f"file ({info['ext'][1:]})" if info["ext"] else "file"
    lines = [
        f"Path: {path}",
        f"Type: {kind}",
        f"Size: {human(info['size'])}",
        f"Created: {when(info['created'])}",
        f"Modified: {when(info['modified'])}",
    ]
    if info["lines"] is not None:
        lines.append(f"Lines: {info['lines']}")
    return "[File Info]\n" + "\n".join(lines)
