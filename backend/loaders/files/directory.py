"""Directory — document loader `directory`."""

import asyncio
import os
from typing import Any, Dict, List

import loaders
from loaders.base import Document, LoaderError, LoaderSpec

LOADER = LoaderSpec(
    type="directory",
    label="Directory",
    icon="🗂️",
    category="Files",
    desc="Load every supported file in a folder",
    source_label="Directory Path",
    placeholder="/path/to/folder",
    aliases=("dir", "folder", "directoryloader"),
    order=80,
)


def _walk(root: str, cfg: Dict[str, Any]) -> List[Document]:
    recursive = str(cfg.get("recursive", True)).lower() != "false"
    max_files = int(cfg.get("max_files", 500))
    docs: List[Document] = []
    seen = skipped = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__")) if recursive else []
        for fname in sorted(filenames):
            if fname.startswith("."):
                continue
            parse = loaders.parser_for(fname)
            if parse is None:
                skipped += 1
                continue
            seen += 1
            if seen > max_files:
                return docs
            path = os.path.join(dirpath, fname)
            try:
                with open(path, "rb") as f:
                    for d in parse(os.path.relpath(path, root), f.read(), cfg):
                        d["metadata"]["directory"] = root
                        docs.append(d)
            except Exception:  # one bad file shouldn't sink the folder
                skipped += 1
    return docs


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    root = os.path.expanduser(source.strip().strip("'\""))
    if not os.path.isdir(root):
        raise LoaderError(f"Folder not found: {root}")
    docs = await asyncio.to_thread(_walk, root, cfg)
    if not docs:
        raise LoaderError(f"No readable files in {root}. Supported: {', '.join(loaders.supported_extensions())}")
    return docs
