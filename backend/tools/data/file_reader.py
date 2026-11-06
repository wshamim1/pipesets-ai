"""File reader — built-in tool `file_reader`."""

import os
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="file_reader",
    name="File Reader",
    icon="📄",
    category="Data & Files",
    description="Reads local text/code files. Input is the file path.",
    default_config={"allowed_dir": "", "max_bytes": 32768},
    order=30,
    parameters=params({"path": {"type": "string", "description": "File path"}}),
    input_param="path",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    allowed_dir = cfg.get("allowed_dir", "").strip()
    max_bytes = int(cfg.get("max_bytes", 32768))
    path = inp.strip()

    # If user entered a prompt like "read /path/to/file" or "summarize test.txt", extract path
    for word in path.split():
        clean_word = word.strip("'\"")
        if (allowed_dir and os.path.exists(os.path.join(allowed_dir, clean_word))) or os.path.exists(clean_word):
            path = clean_word
            break

    # If allowed_dir is set and the path is just a filename (not absolute), resolve it relative to allowed_dir
    if allowed_dir and not os.path.isabs(path):
        path = os.path.join(allowed_dir, path)

    if allowed_dir and not os.path.abspath(path).startswith(os.path.abspath(allowed_dir)):
        return f"[File Reader] Access denied: path is outside allowed directory '{allowed_dir}'"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read(max_bytes)
        suffix = f"\n\n...(truncated to {max_bytes} bytes)" if os.path.getsize(path) > max_bytes else ""
        return f"[File: {path}]\n\n{content}{suffix}"
    except FileNotFoundError:
        return f"[File Reader] File not found: {path}"
    except Exception as e:
        return f"[File Reader] Error: {e}"
