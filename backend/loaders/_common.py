"""Helpers shared by the document loaders."""

import os
from typing import Tuple

import httpx

from loaders.base import LoaderError

USER_AGENT = "Mozilla/5.0 (compatible; PipesetsAI/1.0; +https://github.com/pipesets-ai)"
MAX_FILE_BYTES = 50 * 1024 * 1024


def http_client(timeout: float = 20.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def read_file(source: str) -> Tuple[str, bytes]:
    """→ (file name, bytes) for a local path, with readable errors."""
    path = os.path.expanduser(source.strip().strip("'\""))
    if os.path.isdir(path):
        raise LoaderError(f"{path} is a folder — use the Directory loader.")
    if not os.path.isfile(path):
        raise LoaderError(f"File not found: {path}")
    if os.path.getsize(path) > MAX_FILE_BYTES:
        raise LoaderError(f"{os.path.basename(path)} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    with open(path, "rb") as f:
        return path, f.read()


def decode(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace")
