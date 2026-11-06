"""The sandbox runner service (sandbox_runner.py) and the backend's "remote" sandbox backend:
code goes backend → runner over HTTP with a token, the runner runs it as "container" with
its own engine, and nothing falls back to running inside the backend.

The runner runs for real on a local port; its container engine is replaced by a stand-in that
records what it was asked to run."""
import asyncio
import json
import threading

import pytest

import sandbox_runner
from services import sandbox

TOKEN = "test-sandbox-token"
TOOL = "def run(input_text, config):\n    return input_text\n"


@pytest.fixture
def engine(monkeypatch):
    """Stand-in for the runner's podman: records calls, replies like the tool harness would."""
    calls = []

    def run_container(rt, code, timeout, memory_mb, image, allow_network, requirements=None):
        calls.append({"rt": rt, "timeout": timeout, "memory_mb": memory_mb, "allow_network": allow_network,
                      "requirements": requirements})
        return 0, json.dumps({"result": "ran in container"}), ""

    monkeypatch.setattr(sandbox, "_container_runtime", lambda: "podman")
    monkeypatch.setattr(sandbox, "_run_container", run_container)
    monkeypatch.setattr(sandbox, "_run_local", lambda *a, **k: pytest.fail("must never run locally"))
    return calls


@pytest.fixture
def runner(monkeypatch):
    server = sandbox_runner.make_server("127.0.0.1", 0, TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("SANDBOX_URL", url)
    monkeypatch.setenv("SANDBOX_TOKEN", TOKEN)
    yield url
    server.shutdown()
    server.server_close()


def tool(cfg):
    return asyncio.run(sandbox.run_tool(TOOL, "hi", {}, cfg))


def test_tool_runs_in_the_runner(runner, engine):
    out = tool({"backend": "auto", "timeout": 30, "memory_mb": 512, "allow_network": True,
                "requirements": ["requests", "boto3"]})
    assert out == "ran in container"
    assert engine == [{"rt": "podman", "timeout": 30, "memory_mb": 512, "allow_network": True,
                       "requirements": ["boto3", "requests"]}]
    tool({"backend": "container"})
    assert len(engine) == 2, "'container' means the runner when SANDBOX_URL is set"


def test_runner_caps_limits_and_forces_container(runner, engine):
    status, body = sandbox_runner.run({"code": "x", "cfg": {"backend": "local", "timeout": 99999, "memory_mb": 10**6}})
    assert status == 200 and engine[-1]["timeout"] == sandbox_runner.MAX_TIMEOUT_S
    assert engine[-1]["memory_mb"] == sandbox_runner.MAX_MEMORY_MB
    assert sandbox_runner.run({"code": 1})[0] == 400


def test_runner_errors_reach_the_backend(runner, engine, monkeypatch):
    def broken(*a, **k):
        raise sandbox.SandboxError("Python Sandbox: couldn't install the tool's requirements: nopenope")
    monkeypatch.setattr(sandbox, "_run_container", broken)
    with pytest.raises(RuntimeError, match="nopenope"):
        tool({"backend": "auto", "requirements": ["nopenope"]})


def test_wrong_token_and_runner_down(runner, engine, monkeypatch):
    monkeypatch.setenv("SANDBOX_TOKEN", "wrong")
    with pytest.raises(RuntimeError, match="refused SANDBOX_TOKEN"):
        tool({"backend": "auto"})
    assert engine == []
    monkeypatch.setenv("SANDBOX_URL", "http://127.0.0.1:9")
    with pytest.raises(RuntimeError, match="can't reach the sandbox runner"):
        tool({"backend": "auto"})


def test_remote_without_url(monkeypatch):
    monkeypatch.delenv("SANDBOX_URL", raising=False)
    with pytest.raises(RuntimeError, match="SANDBOX_URL isn't set"):
        tool({"backend": "remote"})


def test_health_and_auth(runner, engine, monkeypatch):
    import httpx
    assert httpx.get(f"{runner}/health").json() == {"engine": "podman"}
    assert httpx.post(f"{runner}/run", json={"code": "x", "cfg": {}}).status_code == 401
    monkeypatch.setattr(sandbox, "_container_runtime", lambda: None)
    assert httpx.get(f"{runner}/health").status_code == 503


def test_runner_needs_a_token():
    with pytest.raises(SystemExit, match="SANDBOX_TOKEN"):
        sandbox_runner.make_server("127.0.0.1", 0, "")


def test_custom_tools_default_to_the_runner(monkeypatch):
    from routers.custom_tools import _sandbox_cfg
    monkeypatch.delenv("SANDBOX_REQUIRE_ISOLATION", raising=False)
    monkeypatch.delenv("SANDBOX_URL", raising=False)
    monkeypatch.delenv("CUSTOM_TOOL_SANDBOX", raising=False)
    assert _sandbox_cfg()["backend"] == "local"
    monkeypatch.setenv("SANDBOX_URL", "http://sandbox:8090")
    assert _sandbox_cfg()["backend"] == "auto"
