"""Webhook-triggered runs and notification channels: API, public trigger, signatures, prompt
templates, execution and alert delivery. A local HTTP server stands in for Slack / the alert
webhook. The tests are steps of one scenario, in order."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from db import get_db_connection
from helpers import mock_flow, run_jobs, run_row
from services import notifier, scheduler, webhooks

PAYLOAD = {"action": "opened", "issue": {"title": "Login broken", "labels": [{"name": "bug"}]}}
TEMPLATE = "New issue: {{body.issue.title}}"
received = []
state = {}   # ids and tokens created by earlier steps


def raw(webhook_id):
    conn = get_db_connection()
    try:
        return dict(conn.execute("SELECT * FROM webhooks WHERE id = ?", (webhook_id,)).fetchone())
    finally:
        conn.close()


def run_once(webhook_id, prompt):
    """Queue a call, then work the queue (the run and its notifications); returns the run row."""
    run_row_id = webhooks.launch(raw(webhook_id), "manual", prompt, "")
    run_jobs()
    return run_row("webhook_runs", run_row_id)


@pytest.fixture(scope="module")
def base():
    """URL of a fake alert receiver; /broken answers 500."""
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(500 if self.path == "/broken" else 200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="module")
def aid(client):
    return client.post("/api/apps", json={"name": "Triage", "description": "", "flow_data": mock_flow("v1")}).json()["id"]


def test_prompt_templates():
    r = webhooks.render_prompt
    assert r("Triage: {{body.issue.title}}", PAYLOAD, {}) == "Triage: Login broken"
    assert r("{{body.issue.labels.0.name}}", PAYLOAD, {}) == "bug"
    assert json.loads(r("{{body}}", PAYLOAD, {})) == PAYLOAD
    assert r("repo={{query.repo}}", {}, {"repo": "pipesets"}) == "repo=pipesets"
    assert r("x{{body.nope.deeper}}y", PAYLOAD, {}) == "xy", "missing fields render empty"
    assert r("{{body}}", webhooks.parse_body(b"plain words"), {}) == "plain words"
    assert r("{{other}}", {}, {}) == "{{other}}", "unknown placeholders stay visible"


def test_signatures():
    sig = webhooks.sign("s3cret", b'{"a":1}')
    assert webhooks.signature_ok("s3cret", b'{"a":1}', {"x-hub-signature-256": sig})
    assert webhooks.signature_ok("s3cret", b'{"a":1}', {"x-pipesets-signature": sig})
    assert webhooks.signature_ok("s3cret", b'{"a":1}', {"x-uaf-signature": sig}), "legacy header"
    assert not webhooks.signature_ok("s3cret", b'{"a":2}', {"x-pipesets-signature": sig})
    assert not webhooks.signature_ok("s3cret", b'{"a":1}', {})


def test_create(client, aid):
    body = {"app_id": aid, "prompt_template": TEMPLATE}
    assert client.post("/api/webhooks", json=body).status_code == 409, "unpublished pipeline refused"
    client.post(f"/api/apps/{aid}/publish")
    r = client.post("/api/webhooks", json=body)
    assert r.status_code == 201
    w = r.json()
    state["wid"], state["token"] = w["id"], w["token"]
    assert w["token"].startswith("whk_") and w["url_path"] == f"/v1/hooks/{w['token']}"
    assert w["name"] == "Triage webhook"
    assert raw(w["id"])["token_prefix"] == w["token"][:12] and raw(w["id"])["token_hash"] != w["token"]
    listed = client.get(f"/api/webhooks?app_id={aid}").json()
    assert len(listed) == 1 and "token" not in listed[0] and "token_hash" not in listed[0]
    assert client.post("/api/webhooks", json={**body, "app_id": "nope"}).status_code == 404


def test_public_trigger(client, env):
    wid, token = state["wid"], state["token"]
    assert client.post("/v1/hooks/whk_nope", json=PAYLOAD).status_code == 404
    assert client.post("/v1/hooks/abc", json=PAYLOAD).status_code == 404
    r = client.post(f"/v1/hooks/{token}", json=PAYLOAD)
    assert r.status_code == 202 and r.json()["run_id"].startswith("whrun_")
    assert "Authorization" not in client.headers, "no login needed"
    runs = client.get(f"/api/webhooks/{wid}/runs").json()
    assert len(runs) == 1 and "Login broken" in (runs[0]["payload_preview"] or "")
    client.patch(f"/api/webhooks/{wid}", json={"prompt_template": "{{body.issue.title}}"})
    assert client.post(f"/v1/hooks/{token}", json={"other": 1}).status_code == 422, "empty render rejected"
    client.patch(f"/api/webhooks/{wid}", json={"prompt_template": TEMPLATE})

    assert webhooks.inflight(wid) == 1, "counted from the queue: the accepted call is still queued"
    env.setattr(webhooks, "MAX_INFLIGHT", 1)
    assert client.post(f"/v1/hooks/{token}", json=PAYLOAD).status_code == 429
    env.setattr(webhooks, "MAX_INFLIGHT", 5)

    client.patch(f"/api/webhooks/{wid}", json={"enabled": False})
    assert client.post(f"/v1/hooks/{token}", json=PAYLOAD).status_code == 403
    client.patch(f"/api/webhooks/{wid}", json={"enabled": True})


def test_signing_secret(client):
    wid, token = state["wid"], state["token"]
    r = client.patch(f"/api/webhooks/{wid}", json={"secret": "s3cret"})
    assert r.json()["has_secret"] and "secret" not in r.json()
    data = json.dumps(PAYLOAD).encode()
    assert client.post(f"/v1/hooks/{token}", content=data).status_code == 401
    assert client.post(f"/v1/hooks/{token}", content=data,
                       headers={"X-Hub-Signature-256": webhooks.sign("s3cret", data)}).status_code == 202
    assert not client.patch(f"/api/webhooks/{wid}", json={"secret": ""}).json()["has_secret"]


def test_rotate_and_test_endpoint(client):
    wid, old = state["wid"], state["token"]
    state["token"] = client.post(f"/api/webhooks/{wid}/rotate").json()["token"]
    assert state["token"] != old
    assert client.post(f"/v1/hooks/{old}", json=PAYLOAD).status_code == 404
    assert client.post(f"/v1/hooks/{state['token']}", json=PAYLOAD).status_code == 202
    r = client.post(f"/api/webhooks/{wid}/test", json={"body": PAYLOAD})
    assert r.status_code == 202 and r.json()["prompt"] == "New issue: Login broken"


def test_execution():
    res = run_once(state["wid"], "New issue: Login broken")
    assert res["status"] == "completed" and res["output_preview"]
    assert webhooks.inflight(state["wid"]) == 0, "earlier accepted calls ran too"
    assert raw(state["wid"])["last_status"] == "completed"


def test_notification_channels_api(client, aid, base):
    assert client.post("/api/notifications", json={"kind": "pager", "url": base}).status_code == 422
    assert client.post("/api/notifications", json={"kind": "slack", "url": "file:///etc/passwd"}).status_code == 422
    assert client.post("/api/notifications", json={"url": base, "events": ["run.exploded"]}).status_code == 422
    assert client.post("/api/notifications", json={"url": base, "events": []}).status_code == 422
    assert client.post("/api/notifications", json={"url": base, "app_id": "nope"}).status_code == 404
    slack = client.post("/api/notifications", json={"kind": "slack", "url": f"{base}/slack"}).json()
    hookch = client.post("/api/notifications", json={"kind": "webhook", "url": f"{base}/generic",
                                                     "events": ["run.failed"], "app_id": aid}).json()
    state["slack"], state["hookch"] = slack["id"], hookch["id"]
    assert slack["name"] == "Slack alerts" and set(slack["events"]) == set(notifier.EVENTS)
    assert slack["url"] == f"{base}/…", "URL masked in responses"

    r = client.post(f"/api/notifications/{slack['id']}/test").json()
    assert r["ok"] and received[-1][0] == "/slack" and "Test notification" in received[-1][1]["text"]
    broken = client.post("/api/notifications", json={"url": f"{base}/broken"}).json()
    r = client.post(f"/api/notifications/{broken['id']}/test").json()
    assert not r["ok"] and "HTTP 500" in r["error"]
    stored = next(ch for ch in client.get("/api/notifications").json() if ch["id"] == broken["id"])
    assert "HTTP 500" in (stored["last_error"] or "")
    client.delete(f"/api/notifications/{broken['id']}")


def test_notifications_from_runs(client):
    received.clear()
    run_once(state["wid"], "fine")
    assert received == [], "completed runs send nothing"

    bad = client.post("/api/apps", json={"name": "No LLM", "description": "", "flow_data": {
        "nodes": [{"id": "t", "type": "start", "data": {}}], "edges": []}}).json()
    client.post(f"/api/apps/{bad['id']}/publish")
    state["bad_app"] = bad["id"]
    bw = client.post("/api/webhooks", json={"app_id": bad["id"]}).json()
    state["bw"] = bw["id"]
    received.clear()
    res = run_once(bw["id"], "go")
    assert res["status"] == "failed" and raw(bw["id"])["last_status"] == "failed"
    assert sorted(p for p, _ in received) == ["/slack"], "only the project-wide channel"
    assert ":x:" in received[0][1]["text"] and "webhook" in received[0][1]["text"]

    received.clear()
    client.patch(f"/api/notifications/{state['hookch']}", json={"app_id": ""})   # widen to every pipeline
    run_once(bw["id"], "go")
    generic = [b for p, b in received if p == "/generic"]
    assert len(generic) == 1 and generic[0]["event"] == "run.failed"
    assert generic[0]["data"]["source"] == "webhook" and generic[0]["data"]["source_id"] == bw["id"]

    received.clear()
    client.patch(f"/api/notifications/{state['slack']}", json={"enabled": False})
    run_once(bw["id"], "go")
    assert [p for p, _ in received] == ["/generic"], "disabled channel skipped"


def test_schedules_notify_too(client):
    client.patch(f"/api/notifications/{state['slack']}", json={"enabled": True})
    sched = client.post("/api/schedules", json={"app_id": state["bad_app"], "cron": "0 2 * * *", "prompt": "go",
                                                "max_failures": 1}).json()
    conn = get_db_connection()
    srow = dict(conn.execute("SELECT * FROM schedules WHERE id = ?", (sched["id"],)).fetchone())
    conn.close()
    received.clear()

    scheduler.launch(srow, "manual")
    run_jobs()
    texts = [b["text"] for p, b in received if p == "/slack"]
    assert any(":x:" in t and "schedule" in t for t in texts)
    assert any("paused after repeated failures" in t for t in texts)


def test_delete(client, aid):
    assert client.delete(f"/api/webhooks/{state['bw']}").json()["deleted"]
    assert client.get(f"/api/webhooks/{state['bw']}/runs").status_code == 404
    client.delete(f"/api/apps/{aid}")
    assert client.get(f"/api/webhooks?app_id={aid}").json() == [], "deleting the pipeline removes its webhooks"
    assert client.post(f"/v1/hooks/{state['token']}", json=PAYLOAD).status_code == 404
    assert client.delete(f"/api/notifications/{state['slack']}").json()["deleted"]
