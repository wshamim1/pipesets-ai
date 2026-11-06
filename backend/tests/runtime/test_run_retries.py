"""
Scheduled and webhook runs on the job queue: retry policy, crash recovery, limits that hold
across replicas, and notification delivery with retries.

``scheduler.run_published`` is replaced with a scripted stand-in, so each attempt's outcome
is chosen by the test; everything around it (jobs, run rows, schedules, notifications) is real.
"""

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from db import get_db_connection
from helpers import mock_flow, run_jobs, run_row
from services import jobs, scheduler, webhooks

OK = {"status": "completed", "output": "done", "meta": {}, "latency_ms": 5, "app_name": "Retry"}
FLAKY = {"status": "failed", "error": "openai: 503 Service Unavailable", "output": "", "meta": {}, "latency_ms": 5}
BLOCKED = {"status": "failed", "error": "[Guardrail: prompt_injection] Prompt injection detected", "output": "",
           "meta": {}, "latency_ms": 5}

script: deque = deque()   # outcomes of the next attempts, in order
calls = []
received = []
flaky_failures = {"left": 0}


@pytest.fixture(autouse=True)
def _scripted_runs(env):
    async def fake_run_published(source, prompt, timeout_ms, run_id=None):
        calls.append(source["id"])
        return 1, dict(script.popleft() if script else OK)
    env.setattr(scheduler, "run_published", fake_run_published)
    env.setenv("JOB_BACKOFF_SECONDS", "0")
    script.clear()
    calls.clear()
    received.clear()


@pytest.fixture(scope="module")
def receiver():
    """Fake alert endpoint: /flaky answers 500 while flaky_failures["left"] > 0."""
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            failing = self.path == "/flaky" and flaky_failures["left"] > 0
            if failing:
                flaky_failures["left"] -= 1
            else:
                received.append((self.path, body))
            self.send_response(500 if failing or self.path == "/down" else 200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="module")
def app_id(client):
    aid = client.post("/api/apps", json={"name": "Retry", "description": "", "flow_data": mock_flow()}).json()["id"]
    client.post(f"/api/apps/{aid}/publish")
    return aid


def _schedule(client, app_id, **body):
    r = client.post("/api/schedules", json={"app_id": app_id, "cron": "0 3 * * *", "prompt": "go", **body})
    assert r.status_code == 201, r.text
    return r.json()


def _sched_row(schedule_id):
    conn = get_db_connection()
    try:
        return dict(conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone())
    finally:
        conn.close()


def _fire(schedule_id):
    return scheduler.launch(_sched_row(schedule_id), "manual")


# ── API ───────────────────────────────────────────────────────────────────────

def test_retries_setting(client, app_id, env):
    assert _schedule(client, app_id)["retries"] == 2, "server default"
    env.setenv("JOB_MAX_RETRIES", "4")
    assert _schedule(client, app_id)["retries"] == 4
    env.setenv("JOB_MAX_RETRIES", "2")
    s = _schedule(client, app_id, retries=-1)
    assert s["retries"] == -1, "until it succeeds"
    assert client.patch(f"/api/schedules/{s['id']}", json={"retries": 0}).json()["retries"] == 0
    for bad in (-2, 11):
        assert client.post("/api/schedules", json={"app_id": app_id, "cron": "0 3 * * *", "prompt": "go",
                                                   "retries": bad}).status_code == 422
        assert client.patch(f"/api/schedules/{s['id']}", json={"retries": bad}).status_code == 422
    hook = client.post("/api/webhooks", json={"app_id": app_id, "retries": 5}).json()
    assert hook["retries"] == 5
    assert client.patch(f"/api/webhooks/{hook['id']}", json={"retries": -1}).json()["retries"] == -1
    assert client.post("/api/webhooks", json={"app_id": app_id, "retries": 11}).status_code == 422


# ── Retry policy ──────────────────────────────────────────────────────────────

def test_a_flaky_run_is_retried_until_it_completes(client, app_id):
    s = _schedule(client, app_id, retries=2)
    script.extend([FLAKY, FLAKY, OK])
    row = run_row("schedule_runs", (rid := _fire(s["id"])))
    assert row["status"] == "queued"
    run_jobs()
    row = run_row("schedule_runs", rid)
    assert row["status"] == "completed" and row["attempts"] == 3 and len(calls) == 3
    sched = _sched_row(s["id"])
    assert sched["last_status"] == "completed" and sched["consecutive_failures"] == 0
    assert jobs.get(row["job_id"])["status"] == "done"


def test_retries_used_up_fail_the_run_once_and_leave_a_dead_job(client, app_id):
    s = _schedule(client, app_id, retries=1, max_failures=5)
    script.extend([FLAKY, FLAKY, OK])
    rid = _fire(s["id"])
    run_jobs()
    row = run_row("schedule_runs", rid)
    assert row["status"] == "failed" and row["attempts"] == 2 and "503" in row["error"] and len(calls) == 2
    assert _sched_row(s["id"])["consecutive_failures"] == 1, "one firing, one failure — not one per attempt"
    job = jobs.get(row["job_id"])
    assert job["status"] == "dead" and "503" in job["last_error"], "in the dead-letter view"

    assert jobs.retry(job["id"], s["tenant_id"], s["project_id"])
    run_jobs()   # script's next outcome is OK
    assert run_row("schedule_runs", rid)["status"] == "completed", "retried from the dead-letter view"


def test_zero_retries_means_one_attempt(client, app_id):
    s = _schedule(client, app_id, retries=0)
    script.extend([FLAKY, OK])
    rid = _fire(s["id"])
    run_jobs()
    assert run_row("schedule_runs", rid)["status"] == "failed" and len(calls) == 1


def test_until_success_keeps_retrying(client, app_id):
    s = _schedule(client, app_id, retries=-1)
    script.extend([FLAKY] * 12 + [OK])
    rid = _fire(s["id"])
    run_jobs()
    row = run_row("schedule_runs", rid)
    assert row["status"] == "completed" and row["attempts"] == 13
    assert jobs.get(row["job_id"])["max_attempts"] == 0


def test_refused_runs_are_not_retried(client, app_id):
    s = _schedule(client, app_id, retries=3)
    script.extend([BLOCKED, OK])
    rid = _fire(s["id"])
    run_jobs()
    row = run_row("schedule_runs", rid)
    assert row["status"] == "failed" and len(calls) == 1 and "Guardrail" in row["error"]
    assert jobs.get(row["job_id"])["status"] == "done", "a refusal is an outcome, not a broken job"


def test_a_waiting_retry_shows_on_the_run_and_blocks_the_next_firing(client, app_id, env):
    env.setenv("JOB_BACKOFF_SECONDS", "600")
    s = _schedule(client, app_id, retries=2)
    script.append(FLAKY)
    rid = _fire(s["id"])
    run_jobs()   # first attempt fails; the retry isn't due for ~10 minutes
    row = run_row("schedule_runs", rid)
    assert row["status"] == "retrying" and "503" in row["error"]
    assert scheduler.is_running(s["id"]), "still in progress while it waits to retry"
    conn = get_db_connection()
    conn.execute("UPDATE schedules SET next_run_at = '2000-01-01T00:00:00Z' WHERE id = ?", (s["id"],))
    conn.commit()
    conn.close()
    assert [(x["id"], overlaps) for x, overlaps in scheduler._claim_due()] == [(s["id"], True)], \
        "overlap seen from the queue, so it holds on every replica"


# ── Crashes ───────────────────────────────────────────────────────────────────

def _crash_a_worker(job_kind="schedule.run"):
    """Claim the next job as a worker that then dies (never renews, never finishes)."""
    job = jobs.claim("dead-worker", [job_kind])
    assert job is not None
    time.sleep(0.3)   # past JOB_LEASE_SECONDS
    return job


def test_a_run_cut_off_by_a_crash_is_retried(client, app_id, env):
    env.setenv("JOB_LEASE_SECONDS", "0.2")
    s = _schedule(client, app_id, retries=2)
    rid = _fire(s["id"])
    _crash_a_worker()
    env.setenv("JOB_LEASE_SECONDS", "60")
    run_jobs()
    row = run_row("schedule_runs", rid)
    assert row["status"] == "completed" and row["attempts"] == 2 and len(calls) == 1
    assert "dead-worker stopped" in jobs.get(row["job_id"])["last_error"]


def test_a_crash_on_the_last_attempt_fails_the_run_and_alerts(client, app_id, receiver, env):
    ch = client.post("/api/notifications", json={"kind": "webhook", "url": f"{receiver}/alerts",
                                                 "events": ["run.failed"]}).json()
    env.setenv("JOB_LEASE_SECONDS", "0.2")
    s = _schedule(client, app_id, retries=0)
    rid = _fire(s["id"])
    _crash_a_worker()
    run_jobs()
    env.setenv("JOB_LEASE_SECONDS", "60")
    row = run_row("schedule_runs", rid)
    assert row["status"] == "failed" and "stopped before the job finished" in row["error"] and not calls
    assert jobs.get(row["job_id"])["status"] == "dead"
    assert _sched_row(s["id"])["consecutive_failures"] == 1
    assert [b["data"]["source_id"] for p, b in received if p == "/alerts"] == [s["id"]]
    client.delete(f"/api/notifications/{ch['id']}")


def test_startup_sweep_spares_runs_with_a_live_job(client, app_id):
    s = _schedule(client, app_id)
    live = _fire(s["id"])
    conn = get_db_connection()   # a row from before runs were jobs
    conn.execute("INSERT INTO schedule_runs (id, schedule_id, tenant_id, project_id, app_id, trigger, status, "
                 "started_at) VALUES ('srun_legacy', ?, ?, ?, ?, 'schedule', 'running', '2026-01-01T00:00:00Z')",
                 (s["id"], s["tenant_id"], s["project_id"], app_id))
    conn.commit()
    conn.close()
    assert scheduler.mark_interrupted_runs() == 1
    assert run_row("schedule_runs", "srun_legacy")["status"] == "interrupted"
    assert run_row("schedule_runs", live)["status"] == "queued", "another replica's queued run is left alone"
    run_jobs()


# ── Webhooks ──────────────────────────────────────────────────────────────────

def test_webhook_calls_retry_with_their_own_setting(client, app_id):
    hook = client.post("/api/webhooks", json={"app_id": app_id, "retries": 1}).json()
    script.extend([FLAKY, OK])
    r = client.post(f"/v1/hooks/{hook['token']}", json={"x": 1})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert webhooks.inflight(hook["id"]) == 1
    run_jobs()
    row = run_row("webhook_runs", r.json()["run_id"])
    assert row["status"] == "completed" and row["attempts"] == 2
    assert webhooks.inflight(hook["id"]) == 0


# ── Notifications ─────────────────────────────────────────────────────────────

def test_a_failing_channel_is_retried_then_delivered(client, app_id, receiver):
    ch = client.post("/api/notifications", json={"kind": "webhook", "url": f"{receiver}/flaky",
                                                 "events": ["run.failed"]}).json()
    flaky_failures["left"] = 2
    s = _schedule(client, app_id, retries=0)
    script.append(FLAKY)
    _fire(s["id"])
    run_jobs()
    assert [b["event"] for p, b in received if p == "/flaky"] == ["run.failed"], "delivered on the third try"
    stored = next(c for c in client.get("/api/notifications").json() if c["id"] == ch["id"])
    assert stored["last_error"] is None and stored["last_sent_at"]
    client.delete(f"/api/notifications/{ch['id']}")


def test_a_dead_channel_ends_in_the_dead_letter_view(client, app_id, receiver):
    ch = client.post("/api/notifications", json={"kind": "webhook", "url": f"{receiver}/down",
                                                 "events": ["run.failed"]}).json()
    s = _schedule(client, app_id, retries=0)
    script.append(FLAKY)
    _fire(s["id"])
    run_jobs()
    conn = get_db_connection()
    dead = [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE kind = 'notify.deliver' AND status = 'dead'")]
    conn.close()
    mine = [j for j in dead if json.loads(j["payload"])["channel_id"] == ch["id"]]
    assert len(mine) == 1 and mine[0]["attempts"] == 3 and "HTTP 500" in mine[0]["last_error"]
    stored = next(c for c in client.get("/api/notifications").json() if c["id"] == ch["id"])
    assert "HTTP 500" in stored["last_error"]
    client.delete(f"/api/notifications/{ch['id']}")
