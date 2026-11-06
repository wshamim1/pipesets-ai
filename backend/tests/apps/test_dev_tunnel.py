"""Settings → Share via ngrok (routers/dev_tunnel.py), with ngrok and its local API faked."""

import pytest

from helpers import hdr
from routers import dev_tunnel

ADMIN = hdr()
ANALYST = hdr("user_analyst")
URL = "https://calm-otter.ngrok-free.app"


class _FakeProc:
    def __init__(self, cmd, exit_code=None):
        self.cmd, self.returncode, self.terminated = cmd, exit_code, False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated, self.returncode = True, 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.fixture
def ngrok(monkeypatch, tmp_path):
    """A fake ngrok: ``state["tunnels"]`` is what its local API reports; started commands are recorded."""
    state = {"tunnels": [], "started": [], "exit_code": None}
    monkeypatch.setenv("PIPESETS_DEV_TUNNEL", "1")
    monkeypatch.setattr(dev_tunnel.shutil, "which", lambda name: "/usr/local/bin/ngrok")
    monkeypatch.setattr(dev_tunnel, "_LOG", tmp_path / "ngrok.log")
    monkeypatch.setattr(dev_tunnel, "_tunnels", lambda: list(state["tunnels"]))
    monkeypatch.setattr(dev_tunnel.time, "sleep", lambda s: None)

    def popen(cmd, **kw):
        proc = _FakeProc(cmd, state["exit_code"])
        state["started"].append(proc)
        if state["exit_code"] is None:
            state["tunnels"] = [{"public_url": URL, "inspect_port": 4040}]
        else:
            (tmp_path / "ngrok.log").write_text("ERR_NGROK_320: the domain is not yours")
        return proc
    monkeypatch.setattr(dev_tunnel.subprocess, "Popen", popen)
    yield state
    dev_tunnel._stop()


def test_only_server_admins(client, ngrok):
    assert client.get("/api/dev/tunnel", headers=ANALYST).status_code == 403
    assert client.post("/api/dev/tunnel/start", json={}, headers=ANALYST).status_code == 403
    assert client.post("/api/dev/tunnel/stop", headers=ANALYST).status_code == 403


def test_off_unless_enabled(client, ngrok, monkeypatch):
    monkeypatch.delenv("PIPESETS_DEV_TUNNEL")
    assert client.get("/api/dev/tunnel", headers=ADMIN).json()["enabled"] is False
    assert client.post("/api/dev/tunnel/start", json={}, headers=ADMIN).status_code == 404
    assert ngrok["started"] == []


def test_start_on_a_static_domain_then_stop(client, ngrok):
    r = client.post("/api/dev/tunnel/start", json={"domain": "https://Calm-Otter.ngrok-free.app/"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["running"], body["ours"], body["public_url"], body["domain"]) == (True, True, URL, "calm-otter.ngrok-free.app")
    proc = ngrok["started"][0]
    assert proc.cmd[:3] == ["ngrok", "http", "5173"] and "--url=https://calm-otter.ngrok-free.app" in proc.cmd

    again = client.post("/api/dev/tunnel/start", json={}, headers=ADMIN)
    assert again.status_code == 200 and len(ngrok["started"]) == 1, "a second start returns the running tunnel"

    ngrok["tunnels"] = []
    assert client.post("/api/dev/tunnel/stop", headers=ADMIN).json()["running"] is False
    assert proc.terminated


def test_a_tunnel_from_a_terminal_is_shown_but_not_replaced(client, ngrok):
    ngrok["tunnels"] = [{"public_url": "https://2980-1-2-3-4.ngrok-free.app", "inspect_port": 4040}]
    status = client.get("/api/dev/tunnel", headers=ADMIN).json()
    assert (status["running"], status["ours"], status["public_url"]) == (True, False, "https://2980-1-2-3-4.ngrok-free.app")
    r = client.post("/api/dev/tunnel/start", json={}, headers=ADMIN)
    assert r.status_code == 409 and "Stop it there first" in r.json()["detail"]
    assert ngrok["started"] == []


def test_ngrok_errors_are_reported(client, ngrok):
    ngrok["exit_code"] = 1
    r = client.post("/api/dev/tunnel/start", json={"domain": "someone-else.ngrok-free.app"}, headers=ADMIN)
    assert r.status_code == 502 and "ERR_NGROK_320" in r.json()["detail"]
    assert client.get("/api/dev/tunnel", headers=ADMIN).json()["ours"] is False


def test_rejects_something_that_isnt_a_domain(client, ngrok):
    r = client.post("/api/dev/tunnel/start", json={"domain": "evil.app --config /etc/x"}, headers=ADMIN)
    assert r.status_code == 400 and ngrok["started"] == []
