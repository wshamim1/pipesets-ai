"""File Lister — built-in tool `file_lister`."""

import os
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="file_lister",
    name="File Lister",
    icon="📁",
    category="Data & Files",
    description="Lists the files and folders in a local directory (name, size, type). Input is the directory path.",
    default_config={"allowed_dir": "", "max_entries": 200},
    order=150,
    parameters=params({"path": {"type": "string", "description": "Directory to list"}}),
    input_param="path",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import asyncio

    path = inp.strip()
    if not path:
        return "[File Lister] Please provide a directory path."
    allowed_dir = (cfg.get("allowed_dir") or "").strip()
    if allowed_dir:
        root = os.path.realpath(allowed_dir)
        path = os.path.realpath(os.path.join(root, path) if not os.path.isabs(path) else path)
        if os.path.commonpath([root, path]) != root:
            return f"[File Lister] Access denied: path is outside allowed directory '{allowed_dir}'"

    def list_dir() -> list:
        entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        out = []
        for e in entries:
            if e.is_dir(follow_symlinks=False):
                out.append((e.name, "dir", 0))
            else:
                out.append((e.name, "file", e.stat(follow_symlinks=False).st_size))
        return out

    try:
        rows = await asyncio.to_thread(list_dir)
    except FileNotFoundError:
        return f"[File Lister] Directory not found: {path}"
    except PermissionError:
        return f"[File Lister] Permission denied: {path}"
    except Exception as e:
        return f"[File Lister] Error: {e}"

    if not rows:
        return f"[File Lister] Directory is empty: {path}"

    max_entries = int(cfg.get("max_entries", 200))
    shown, truncated = rows[:max_entries], rows[max_entries:]

    def size(n: int) -> str:
        return f"{n/1024/1024:.1f} MB" if n >= 1024 * 1024 else f"{n/1024:.1f} KB" if n >= 1024 else f"{n} B"

    body = "\n".join(f"{'📁' if kind == 'dir' else '📄'} {name}{'/' if kind == 'dir' else f'  ({size(n)})'}"
                     for name, kind, n in shown)
    suffix = f"\n\n… and {len(truncated)} more (max_entries={max_entries})" if truncated else ""
    return f"[Directory: {path}]  {len(rows)} entr{'y' if len(rows) == 1 else 'ies'}\n\n{body}{suffix}"
