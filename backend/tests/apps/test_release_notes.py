"""What's new (services/release_notes.py, GET /api/release-notes): the latest commit from git — message
without trailers, author name only, files counted per area — else the release_notes.json a build wrote,
else nothing."""
import json
import subprocess

import pytest

from helpers import hdr
from services import release_notes


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Ana Dev")
    git(tmp_path, "config", "user.email", "ana@example.com")
    for path, text in {"backend/api.py": "a\nb\n", "backend/tests/test_api.py": "t\n", "frontend/src/App.tsx": "x\n",
                       "README.md": "r\n"}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "First")
    (tmp_path / "backend/api.py").write_text("a\nc\nd\n")
    git(tmp_path, "commit", "-q", "-am",
        "Add the What's new panel\n\nShows the latest commit.\n\nCo-Authored-By: Bot <bot@example.com>")
    monkeypatch.setattr(release_notes, "REPO_DIR", str(tmp_path))
    return tmp_path


def test_latest_commit_from_git(repo):
    notes = release_notes.latest(1)
    assert notes["source"] == "git" and len(notes["commits"]) == 1
    c = notes["commits"][0]
    assert c["subject"] == "Add the What's new panel" and c["body"] == "Shows the latest commit."
    assert c["author"] == "Ana Dev" and "ana@example.com" not in json.dumps(c), "never the email"
    assert len(c["short"]) >= 7 and len(c["hash"]) == 40
    assert c["files"] == [{"path": "backend/api.py", "added": 2, "removed": 1}]
    assert c["areas"] == [{"area": "Backend", "files": 1, "added": 2, "removed": 1}]


def test_areas_group_files(repo):
    first = release_notes.latest(2)["commits"][1]
    assert {a["area"]: a["files"] for a in first["areas"]} == {"Backend": 1, "Tests": 1, "Frontend": 1, "Project": 1}


def test_falls_back_to_the_build_file_then_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(release_notes, "REPO_DIR", str(tmp_path / "not-a-repo"))
    monkeypatch.setattr(release_notes, "BUNDLED", str(tmp_path / "release_notes.json"))
    release_notes._bundled.cache_clear()
    assert release_notes.latest() == {"source": "none", "commits": []}

    (tmp_path / "release_notes.json").write_text(json.dumps({"commits": [
        {"hash": "abc", "short": "abc", "date": "2026-11-04T10:00:00+00:00", "author": "Ana", "subject": "Ship it",
         "body": "Body\nSigned-off-by: Ana", "files": [{"path": "frontend/x.ts", "added": 3, "removed": 0}]}]}))
    release_notes._bundled.cache_clear()
    notes = release_notes.latest()
    assert notes["source"] == "build" and notes["commits"][0]["body"] == "Body"
    assert notes["commits"][0]["areas"] == [{"area": "Frontend", "files": 1, "added": 3, "removed": 0}]
    release_notes._bundled.cache_clear()


def test_endpoint(client, repo):
    r = client.get("/api/release-notes", headers=hdr())
    assert r.status_code == 200 and r.json()["commits"][0]["subject"] == "Add the What's new panel"
    assert len(client.get("/api/release-notes?limit=50", headers=hdr()).json()["commits"]) == 2, "capped at what exists"
