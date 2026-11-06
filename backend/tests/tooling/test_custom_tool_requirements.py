"""Per-tool requirements for custom tools: spec validation, storage through the API, and how the
sandbox installs them — a cached venv (local) or a cached image (container), never the backend.
The package-install route into the backend is gone.

Installs are not run for real (no network in tests): subprocess.run is replaced where a venv
or image would be built, and the tool itself runs on the backend's Python."""
import asyncio
import json
import os
import subprocess
import sys

import pytest

from helpers import hdr
from services import sandbox

P = hdr()
TOOL = "import sys\ndef run(input_text, config):\n    return sys.executable\n"


@pytest.fixture(autouse=True)
def _clean_caches():
    sandbox._known_images.clear()
    yield
    sandbox._known_images.clear()


def test_normalize_requirements():
    assert sandbox.normalize_requirements(["requests>=2.31", " boto3 ", "", "requests >= 2.31", "httpx[http2]"]) == \
        ["boto3", "httpx[http2]", "requests>=2.31"], "validated, de-duplicated, sorted"
    assert sandbox.normalize_requirements("requests\nhttpx,boto3") == ["boto3", "httpx", "requests"]
    for bad, why in (("-r /etc/passwd", "pip options"), ("--index-url=https://evil.example", "pip options"),
                     ("pkg @ https://evil.example/pkg.whl", "URLs"), ("../local/path", "valid requirement"),
                     ("git+https://github.com/x/y", "valid requirement")):
        with pytest.raises(ValueError, match=why):
            sandbox.normalize_requirements([bad])
    with pytest.raises(ValueError, match="At most"):
        sandbox.normalize_requirements([f"pkg{i}" for i in range(sandbox.MAX_REQUIREMENTS + 1)])


def test_requirements_stored_through_the_api(client):
    r = client.post("/api/custom-tools", json={"name": "fetch", "code": TOOL, "requirements": ["requests", "httpx>=0.27"]},
                    headers=P)
    assert r.status_code == 201 and r.json()["requirements"] == ["httpx>=0.27", "requests"]
    tool_id = r.json()["id"]
    listed = next(t for t in client.get("/api/custom-tools", headers=P).json()["tools"] if t["id"] == tool_id)
    assert listed["requirements"] == ["httpx>=0.27", "requests"]

    assert client.put(f"/api/custom-tools/{tool_id}", json={"name": "fetch2"}, headers=P).json()["requirements"] == \
        ["httpx>=0.27", "requests"], "unchanged unless sent"
    assert client.put(f"/api/custom-tools/{tool_id}", json={"requirements": []}, headers=P).json()["requirements"] == []

    bad = client.post("/api/custom-tools", json={"name": "x", "code": TOOL, "requirements": ["-e ."]}, headers=P)
    assert bad.status_code == 422 and "pip options" in json.dumps(bad.json())
    assert client.post("/api/custom-tools/execute-code", json={"code": TOOL, "input_text": "",
                                                               "requirements": ["x @ file:///etc"]},
                       headers=P).status_code == 422


def test_backend_install_route_is_gone(client):
    assert client.post("/api/custom-tools/install", data={"packages": "requests"}, headers=P).status_code in (404, 405)


def test_local_venv_built_once_and_used(monkeypatch, tmp_path):
    monkeypatch.setenv("PIPESETS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sandbox, "data_path", lambda *parts: os.path.join(str(tmp_path), *parts))
    calls = []
    real_run = subprocess.run

    def fake_run(cmd, **kw):
        if "-m" in cmd and ("venv" in cmd or "pip" in cmd):
            calls.append(cmd)
            assert "PIPESETS_MASTER_KEY" not in kw["env"], "installers get a scrubbed env"
            if "venv" in cmd:
                os.makedirs(cmd[-1], exist_ok=True)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kw)

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    python = sandbox._tool_venv(["requests"])
    assert calls[0][1:3] == ["-m", "venv"] and calls[0][-1] == os.path.dirname(os.path.dirname(python))
    assert calls[1] == [python, "-m", "pip", "install", "--disable-pip-version-check", "requests"], \
        "specs are arguments, not a shell string"
    assert sandbox._tool_venv(["requests"]) == python and len(calls) == 2, "reused"
    assert sandbox._tool_venv(["httpx"]) != python, "another set gets its own venv"


def test_local_venv_failure_cleans_up(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "data_path", lambda *parts: os.path.join(str(tmp_path), *parts))

    def fake_run(cmd, **kw):
        if "venv" in cmd:
            os.makedirs(cmd[-1], exist_ok=True)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", "ERROR: No matching distribution found for nopenope")

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    with pytest.raises(sandbox.SandboxError, match="No matching distribution"):
        sandbox._tool_venv(["nopenope"])
    assert not os.listdir(tmp_path / "tool-envs"), "half-built venv removed, so the next run retries"


def test_tool_runs_on_its_venv_python(monkeypatch):
    seen = []
    monkeypatch.setattr(sandbox, "_tool_venv", lambda reqs: seen.append(reqs) or sys.executable)
    cfg = {"backend": "local", "timeout": 20, "requirements": ["requests"]}
    out = asyncio.run(sandbox.run_tool(TOOL, "", {}, cfg))
    assert seen == [["requests"]] and out == sys.executable
    seen.clear()
    asyncio.run(sandbox.run_tool(TOOL, "", {}, {"backend": "local", "timeout": 20}))
    assert seen == [], "no requirements → no venv"


def test_container_image_built_once_with_exec_form(monkeypatch):
    commands = []

    def fake_run(cmd, **kw):
        commands.append((cmd, kw.get("input")))
        if cmd[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0 if cmd[3] == sandbox.DEFAULT_IMAGE else 1, "", "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": "ok"}), "")

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    cfg = {"backend": "container", "requirements": ["requests>=2", "boto3"]}
    monkeypatch.setattr(sandbox, "_container_runtime", lambda: "docker")
    assert asyncio.run(sandbox.run_tool(TOOL, "", {}, cfg)) == "ok"
    builds = [(c, i) for c, i in commands if c[1] == "build"]
    assert len(builds) == 1
    (build_cmd, dockerfile), = builds
    tag = build_cmd[3]
    assert tag.startswith("pipesets-tool:") and build_cmd[-1] == "-"
    assert dockerfile.splitlines() == [
        f"FROM {sandbox.DEFAULT_IMAGE}",
        'RUN ["pip", "install", "--no-cache-dir", "--disable-pip-version-check", "boto3", "requests>=2"]']
    run_cmd = next(c for c, _ in commands if c[1] == "run")
    assert tag in run_cmd and "--network" in run_cmd and "--read-only" in run_cmd

    commands.clear()
    asyncio.run(sandbox.run_tool(TOOL, "", {}, cfg))
    assert not any(c[1] == "build" for c, _ in commands), "image reused"
