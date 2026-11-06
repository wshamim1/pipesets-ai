"""release_notes.py — what's in this build, for the "What's new" panel (GET /api/release-notes).

The notes are the latest commits: subject, body, date, author name (never the email) and the files
they changed, counted per area of the codebase. They come from git when the code runs from a checkout;
a Docker image or desktop build has no ``.git``, so ``scripts/write_release_notes.py`` writes
``release_notes.json`` next to the backend before the build and it's read instead. Neither → no notes.
"""

import json
import os
import subprocess
from functools import lru_cache
from typing import Any, Dict, List, Optional

from paths import CODE_DIR

BUNDLED = os.path.join(CODE_DIR, "release_notes.json")
REPO_DIR = os.path.dirname(CODE_DIR)
MAX_COMMITS = 20
SEP, END = "\x1f", "\x1e"

# Path prefix → area shown in the panel, first match wins
AREAS = [("backend/tests/", "Tests"), ("frontend/src/test", "Tests"), ("backend/", "Backend"),
         ("frontend/", "Frontend"), ("desktop/", "Desktop app"), ("deploy/", "Deployment"), ("docs/", "Docs"),
         ("sdk/", "SDK"), ("examples/", "Examples")]


def _area(path: str) -> str:
    if ".test." in path or "/tests/" in path:
        return "Tests"
    return next((name for prefix, name in AREAS if path.startswith(prefix)), "Project")


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", REPO_DIR, *args], capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout


def from_git(limit: int) -> Optional[List[Dict[str, Any]]]:
    """The last ``limit`` commits with their changed files, or None when there's no git checkout."""
    log = _git("log", f"-{limit}", "--no-merges", f"--format={END}%H{SEP}%h{SEP}%aI{SEP}%an{SEP}%s{SEP}%b{SEP}", "--numstat")
    if log is None:
        return None
    commits = []
    for chunk in log.split(END)[1:]:
        full, short, date, author, subject, body, stats = (chunk.split(SEP) + [""] * 7)[:7]
        files = []
        for line in stats.strip().splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                added, removed, path = parts
                files.append({"path": path, "added": int(added) if added.isdigit() else 0,
                              "removed": int(removed) if removed.isdigit() else 0})
        commits.append(summarise({"hash": full, "short": short, "date": date, "author": author,
                                  "subject": subject.strip(), "body": body.strip(), "files": files}))
    return commits


def summarise(commit: Dict[str, Any]) -> Dict[str, Any]:
    """Add per-area counts and drop trailer lines (Co-Authored-By, Signed-off-by) from the body."""
    areas: Dict[str, Dict[str, int]] = {}
    for f in commit.get("files") or []:
        a = areas.setdefault(_area(f["path"]), {"files": 0, "added": 0, "removed": 0})
        a["files"] += 1
        a["added"] += f.get("added", 0)
        a["removed"] += f.get("removed", 0)
    body = "\n".join(line for line in (commit.get("body") or "").splitlines()
                     if not line.lower().startswith(("co-authored-by:", "signed-off-by:"))).strip()
    return {**commit, "body": body, "areas": [{"area": k, **v} for k, v in sorted(areas.items(), key=lambda kv: -kv[1]["files"])]}


@lru_cache(maxsize=1)
def _bundled() -> Optional[List[Dict[str, Any]]]:
    try:
        with open(BUNDLED, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return [summarise(c) for c in data.get("commits") or []]


def latest(limit: int = 1) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 1), MAX_COMMITS))
    commits = from_git(limit)
    if commits is not None:
        return {"source": "git", "commits": commits}
    bundled = _bundled()
    if bundled is not None:
        return {"source": "build", "commits": bundled[:limit]}
    return {"source": "none", "commits": []}
