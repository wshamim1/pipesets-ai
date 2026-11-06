"""File Writer — built-in tool `file_writer`."""

import os
from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, params, tool_path

TOOL = ToolSpec(
    id="file_writer",
    name="File Writer",
    icon="✍️",
    category="Data & Files",
    description="Writes/saves text to a local file (create, overwrite or append).",
    default_config={"path": "", "allowed_dir": "", "mode": "overwrite"},
    order=140,
    selects={
        "mode": Select("Mode", (("overwrite", "Overwrite"), ("append", "Append"))),
    },
    parameters=params(
        {"content": {"type": "string", "description": "The file content"}},
        {"path": {"type": "string", "description": "File path to write (relative to allowed_dir when one is set)"},
         "mode": enum(["overwrite", "append"], "overwrite = replace the file, append = add to its end")},
    ),
    input_param="content",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import asyncio

    content = inp.strip()
    if not content:
        return "[File Writer] No content provided. Pass the file content (or text) as input."

    path, error = tool_path((cfg.get("path") or "").strip(), cfg, "File Writer")
    if error:
        return error
    mode = (cfg.get("mode") or "overwrite").strip().lower()

    def write() -> str:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        existed = os.path.exists(path)
        with open(path, "a" if mode == "append" else "w", encoding="utf-8") as fh:
            fh.write(content if mode == "append" and existed else content)
        return (
            f"[File Writer] {'Appended to' if mode == 'append' and existed else 'Wrote'} {path}\n"
            f"Size: {len(content.encode('utf-8'))} bytes"
        )

    try:
        return await asyncio.to_thread(write)
    except Exception as e:
        return f"[File Writer] Error: {e}"
