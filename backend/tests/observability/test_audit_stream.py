"""Audit log streaming (services/audit_stream.py): sink admin, ordered at-least-once delivery to a real HTTP
receiver, HMAC signatures, retry with backoff without losing entries, workspace isolation, and the Splunk HEC /
Datadog formats."""
import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from helpers import serve
from services import audit_stream

received = []
fail = {"on": False}
receiver = FastAPI()


@receiver.post("/hook")
async def hook(request: Request):
    if fail["on"]:
        return JSONResponse({"error": "down"}, status_code=503)
    received.append({"body": await request.body(), "headers": dict(request.headers)})
    return {"ok": True}


@pytest.fixture(scope="module", autouse=True)
def _setup(env):
    env.setenv("AUTH_MODE", "session")
    env.setenv("EXTERNAL_AGENT_ALLOW_PRIVATE", "1")       # the receiver is on 127.0.0.1
    env.setattr(audit_stream, "LAG_SECONDS", 0)


@pytest.fixture(scope="module")
def url():
    gen = serve(receiver)
    base = next(gen)
    yield f"{base}/hook"
    next(gen, None)


def signup(client, email):
    d = client.post("/api/auth/signup", json={"email": email, "password": "long-password", "display_name": "x"}).json()
    return {"Authorization": f"Bearer {d['token']}", "x-tenant-id": d["tenants"][0]["id"]}


@pytest.fixture(scope="module")
def A(client):
    return signup(client, "stream-a@example.com")


def act(client, H, n=1):
    """n audited actions (secret creates) in H's workspace."""
    for i in range(n):
        assert client.post("/api/secrets", headers=H, json={"name": f"s{i}-{len(received)}", "value": "v",
                                                            "kind": "tool"}).status_code in (200, 201)


def deliver():
    return asyncio.run(audit_stream.deliver_due())


def events():
    return [e for r in received for e in json.loads(r["body"])["events"]]


@pytest.fixture(scope="module")
def sink(client, A, url):
    act(client, A, 2)                                     # happens before the sink: not streamed (start=now)
    r = client.post("/api/audit-log/sinks", headers=A, json={"name": "SIEM", "kind": "webhook",
                                                            "url": url + "?key=SECRETQ", "token": "hmac-key"})
    assert r.status_code == 201, r.text
    return r.json()


def test_admin_view_hides_secrets_and_needs_owner(client, A, sink):
    assert sink["url"].endswith("/hook") and "SECRETQ" not in json.dumps(sink) and sink["token_set"]
    assert "hmac-key" not in json.dumps(client.get("/api/audit-log/sinks", headers=A).json())
    B = signup(client, "stream-b@example.com")
    assert client.get("/api/audit-log/sinks", headers=B).json()["sinks"] == []
    assert client.delete(f"/api/audit-log/sinks/{sink['id']}", headers=B).status_code == 404
    for bad in ({"kind": "ftp", "url": "https://x"}, {"kind": "webhook", "url": "http://example.com/h"},
                {"kind": "splunk_hec", "url": "https://splunk.example.com/services/collector/event"}):
        assert client.post("/api/audit-log/sinks", headers=A, json=bad).status_code == 400


def test_delivers_new_entries_in_order_signed(client, A, sink):
    received.clear()
    act(client, A, 3)
    assert deliver() >= 3
    got = events()
    actions = [e["action"] for e in got]
    assert actions.count("secret.create") == 3 and "audit_sink.create" in actions
    assert [e["created_at"] for e in got] == sorted(e["created_at"] for e in got)
    assert all(e["tenant_id"] == A["x-tenant-id"] for e in got)
    body, headers = received[0]["body"], received[0]["headers"]
    assert headers["x-pipesets-signature"] == "sha256=" + hmac.new(b"hmac-key", body, hashlib.sha256).hexdigest()
    assert deliver() == 0, "nothing new, nothing re-sent"
    s = client.get("/api/audit-log/sinks", headers=A).json()["sinks"][0]
    assert s["delivered"] == len(got) and s["last_delivered_at"] and not s["last_error"]


def test_outage_retries_without_losing_entries(client, A, sink):
    received.clear()
    fail["on"] = True
    act(client, A, 2)
    assert deliver() == 0
    s = client.get("/api/audit-log/sinks", headers=A).json()["sinks"][0]
    assert s["failures"] == 1 and "503" in s["last_error"] and s["next_attempt_at"]
    fail["on"] = False
    assert deliver() == 0, "backing off: not retried before next_attempt_at"
    # Resuming (or waiting out the backoff) retries; the same entries arrive
    client.patch(f"/api/audit-log/sinks/{sink['id']}", headers=A, json={"enabled": True})
    assert deliver() >= 2 and [e["action"] for e in events()].count("secret.create") == 2


def test_paused_sink_gets_nothing_and_test_event(client, A, sink):
    client.patch(f"/api/audit-log/sinks/{sink['id']}", headers=A, json={"enabled": False})
    received.clear()
    act(client, A, 1)
    assert deliver() == 0 and received == []
    r = client.post(f"/api/audit-log/sinks/{sink['id']}/test", headers=A).json()
    assert r["ok"] and events()[0]["action"] == "audit_sink.test"
    client.patch(f"/api/audit-log/sinks/{sink['id']}", headers=A, json={"enabled": True})
    received.clear()
    assert deliver() >= 1, "entries written while paused are delivered on resume"


def test_start_all_backfills(client, A, url):
    received.clear()
    r = client.post("/api/audit-log/sinks", headers=A, json={"kind": "webhook", "url": url, "start": "all"})
    deliver()
    assert len([e for e in events() if e["action"] == "secret.create"]) >= 8
    client.delete(f"/api/audit-log/sinks/{r.json()['id']}", headers=A)


def test_splunk_and_datadog_formats():
    ev = [{"id": "a1", "created_at": "2026-11-23T10:00:00", "actor": "u1", "action": "secret.create",
           "target_id": "s", "outcome": "success", "status": 200, "method": "POST", "path": "/x", "project_id": "p", "ip": ""}]
    url, body, headers = audit_stream.build_request("splunk_hec", "https://s/services/collector/event", "TOK", "t1", ev)
    line = json.loads(body.decode().splitlines()[0])
    assert headers["Authorization"] == "Splunk TOK" and line["sourcetype"] == "pipesets:audit"
    assert line["event"]["tenant_id"] == "t1" and line["time"] == 1795428000.0
    url, body, headers = audit_stream.build_request("datadog", audit_stream.DATADOG_DEFAULT, "DDKEY", "t1", ev)
    item = json.loads(body)[0]
    assert headers["DD-API-KEY"] == "DDKEY" and item["ddsource"] == "pipesets" and "tenant:t1" in item["ddtags"]
    assert item["message"] == "secret.create success by u1"
