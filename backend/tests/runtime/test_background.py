"""
Background work beyond the queue itself: periodic loops taking turns across processes, the job
purge, the dead-letter API, Human Gate timeouts and stale agent runs (services/gates.py).
"""

import asyncio
import json
import time
from datetime import datetime, timedelta

import pytest

from db import get_db_connection
from helpers import hdr, run_jobs
from services import gates, jobs
from services.pipeline_runner import _build_master_request

NOW = datetime.utcnow


def _sql(sql, params=()):
    conn = get_db_connection()
    try:
        cur = conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()] if sql.lstrip().upper().startswith("SELECT") else cur.rowcount
        conn.commit()
        return rows
    finally:
        conn.close()


def _run(run_id):
    return _sql("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,))[0]


@pytest.fixture(autouse=True)
def _clean(env):
    env.setenv("JOB_BACKOFF_SECONDS", "0")
    _sql("DELETE FROM jobs")
    _sql("DELETE FROM leases")


# ── Periodic loops ────────────────────────────────────────────────────────────

def test_one_process_takes_each_turn():
    assert jobs.take_turn("t", "a", 0.3)
    assert not jobs.take_turn("t", "a", 0.3), "not even the last holder before the period is up"
    assert not jobs.take_turn("t", "b", 0.3)
    time.sleep(0.35)
    assert jobs.take_turn("t", "b", 0.3)


def test_loops_in_several_processes_run_once_per_period():
    ran = []

    async def tick():
        ran.append(time.monotonic())

    async def go():
        loops = [asyncio.create_task(jobs.every("demo", 0.3, tick)) for _ in range(4)]   # four "replicas"
        await asyncio.sleep(1.0)
        for t in loops:
            t.cancel()
        await asyncio.gather(*loops, return_exceptions=True)

    asyncio.run(go())
    assert 2 <= len(ran) <= 4, ran
    # A double turn lands ~0 s apart; scheduling jitter under load can eat well over 10 ms, so
    # don't demand the full period between runs.
    assert all(b - a >= 0.2 for a, b in zip(ran, ran[1:])), "never two runs in one period"


def test_a_failing_periodic_keeps_its_loop():
    calls = []

    async def boom():
        calls.append(1)
        raise RuntimeError("boom")

    async def go():
        t = asyncio.create_task(jobs.every("boom", 0.1, boom))
        await asyncio.sleep(0.45)
        t.cancel()
        await asyncio.gather(t, return_exceptions=True)

    asyncio.run(go())
    assert len(calls) >= 2


def test_every_background_task_registers():
    jobs.load_handlers()
    assert {"scheduler.tick", "runs.orphans", "audit.purge", "gates.sweep", "jobs.purge"} <= set(jobs._periodic)
    assert "agent.resume" in jobs._handlers


# ── Purge ─────────────────────────────────────────────────────────────────────

def _job(status, finished_days_ago=None, project="proj_research", kind="schedule.run", payload=None):
    job_id = jobs.enqueue(kind, payload or {"schedule_id": "gone"}, tenant_id="tenant_demo", project_id=project)
    if status != "queued":
        finished = jobs._after(-finished_days_ago * 86400) if finished_days_ago is not None else None
        _sql("UPDATE jobs SET status = ?, finished_at = ?, last_error = 'boom', attempts = 3 WHERE id = ?",
             (status, finished, job_id))
    return job_id


def test_purge_keeps_recent_and_dead_jobs_longer(env):
    old_done, new_done = _job("done", 8), _job("done", 1)
    old_dead, new_dead = _job("dead", 31), _job("dead", 8)
    queued = _job("queued")
    assert jobs.purge_finished() == {"done": 1, "dead": 1}
    left = {r["id"] for r in _sql("SELECT id FROM jobs")}
    assert left == {new_done, new_dead, queued}
    assert old_done not in left and old_dead not in left

    env.setenv("JOB_KEEP_DEAD_DAYS", "0")
    assert jobs.purge_finished() == {"done": 0}, "0 keeps dead jobs forever"


# ── Dead-letter API ───────────────────────────────────────────────────────────

def test_dead_letter_view_lists_retries_and_discards(client):
    dead = _job("dead", 0)
    other = _job("dead", 0, project="proj_other")
    _job("done", 0)

    r = client.get("/api/jobs", headers=hdr())
    assert r.status_code == 200, r.text
    body = r.json()
    assert [j["id"] for j in body["jobs"]] == [dead], "only this project's dead jobs"
    job = body["jobs"][0]
    assert job["label"] == "Scheduled run · (deleted)" and job["last_error"] == "boom"
    assert "payload" not in job
    assert body["counts"]["dead"] == 1 and body["counts"]["done"] == 1

    assert client.post(f"/api/jobs/{other}/retry", headers=hdr()).status_code == 409, "another project's job"
    assert client.post(f"/api/jobs/{dead}/retry", headers=hdr()).status_code == 200
    assert jobs.get(dead)["status"] == "queued" and jobs.get(dead)["attempts"] == 0
    assert client.post(f"/api/jobs/{dead}/retry", headers=hdr()).status_code == 409, "no longer dead"
    assert client.delete(f"/api/jobs/{dead}", headers=hdr()).status_code == 409, "queued jobs can't be discarded"

    run_jobs()   # its schedule is gone, so it finishes as done
    second = _job("dead", 0)
    assert client.delete(f"/api/jobs/{second}", headers=hdr()).status_code == 200
    assert jobs.get(second) is None


def test_dead_letter_retry_needs_write_access(client):
    dead = _job("dead", 0, project="proj_support")
    viewer = hdr("user_viewer", project="proj_support")   # apps:read only
    assert [j["id"] for j in client.get("/api/jobs", headers=viewer).json()["jobs"]] == [dead]
    assert client.post(f"/api/jobs/{dead}/retry", headers=viewer).status_code == 403
    assert client.delete(f"/api/jobs/{dead}", headers=viewer).status_code == 403


# ── Human Gate timeouts ───────────────────────────────────────────────────────

def _paused(run_id, on_timeout, expired=True, app_id=None):
    gate = {"key": "gate:final", "agent": "Master Agent", "gate_type": "approval", "label": "Human review",
            "output": "draft", "on_timeout": on_timeout, "paused_at": NOW().isoformat(),
            "expires_at": (NOW() + timedelta(hours=-1 if expired else 1)).isoformat()}
    _sql("DELETE FROM agent_runs WHERE run_id = ?", (run_id,))
    _sql("INSERT INTO agent_runs (run_id, goal, strategy, final_answer, steps, success, status, app_id, tenant_id, "
         "project_id, user_id, fingerprint, checkpoint, pending_gate, created_at, updated_at) VALUES "
         "(?, 'g', 'sequential', '', '[]', 0, 'paused', ?, 'tenant_demo', 'proj_research', 'user_admin', 'f', '{}', ?, ?, ?)",
         (run_id, app_id, json.dumps(gate), NOW().isoformat(), NOW().isoformat()))


@pytest.fixture(scope="module")
def channel(client):
    r = client.post("/api/notifications", headers=hdr(), json={
        "name": "ops", "kind": "webhook", "url": "https://example.invalid/hook",
        "events": ["run.failed", "gate.escalated"]})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _notifications():
    return [json.loads(r["payload"])["event"] for r in _sql("SELECT payload FROM jobs WHERE kind = 'notify.deliver'")]


def test_an_expired_reject_gate_ends_the_run(channel):
    _paused("gate-reject", "reject", app_id="app_x")
    _paused("gate-waiting", "reject", expired=False, app_id="app_x")
    assert gates.sweep() == {"reject": 1}
    row = _run("gate-reject")
    assert row["status"] == "rejected" and "Review timed out" in row["error"] and row["pending_gate"] is None
    assert json.loads(row["checkpoint"])["gates"]["gate:final"]["action"] == "reject"
    assert _run("gate-waiting")["status"] == "paused", "not expired yet"
    assert _notifications() == ["run.failed"]


def test_an_escalated_gate_alerts_once_and_keeps_waiting(channel):
    _paused("gate-escalate", "escalate", app_id="app_x")
    assert gates.sweep() == {"escalate": 1}
    assert gates.sweep() == {}, "handled once"
    row = _run("gate-escalate")
    assert row["status"] == "paused" and json.loads(row["pending_gate"])["timed_out_at"]
    assert _notifications() == ["gate.escalated"]


def test_an_approve_gate_on_an_editor_run_waits_for_its_next_resume():
    _paused("gate-editor", "approve")
    assert gates.sweep() == {"approve": 1}
    assert _run("gate-editor")["status"] == "paused"
    assert not _sql("SELECT id FROM jobs WHERE kind = 'agent.resume'"), "no app to rebuild the run from"


GATED_FLOW = {
    "nodes": [{"id": "m", "type": "master_agent", "data": {"provider": "mock", "model": "mock-gpt-4"}},
              {"id": "c", "type": "child_agent", "data": {"provider": "mock", "model": "mock-gpt-4", "role": "writer",
                                                           "label": "W"}},
              {"id": "g", "type": "human_gate", "data": {"timeout_hours": 0.00001, "on_timeout": "approve"}}],
    "edges": [{"source": "m", "target": "c"}, {"source": "g", "target": "m"}],
}


def test_an_approve_gate_on_a_published_app_resumes_the_run(client):
    from routers.agents import run_master
    from services.request_context import RequestContext

    app_id = client.post("/api/apps", headers=hdr(), json={"name": "Gated", "description": "",
                                                           "flow_data": GATED_FLOW}).json()["id"]
    assert client.post(f"/api/apps/{app_id}/publish", headers=hdr()).status_code == 200
    req = _build_master_request("Say hi", GATED_FLOW["nodes"], GATED_FLOW["edges"], {})
    ctx = RequestContext(tenant_id="tenant_demo", project_id="proj_research", user_id="user_admin")
    res = asyncio.run(run_master(req, ctx, app_id=app_id))
    assert res.status == "paused"
    time.sleep(0.05)   # past the gate's 36 ms

    assert gates.sweep() == {"approve": 1}
    run_jobs()
    row = _run(res.run_id)
    assert row["status"] == "completed", row["error"]
    decision = json.loads(row["checkpoint"])["gates"]["gate:final"]
    assert decision["action"] == "approve" and decision["comment"] == "Review timed out"


# ── Stale agent runs ──────────────────────────────────────────────────────────

def test_only_runs_that_stopped_heartbeating_are_interrupted():
    from routers.agents import mark_interrupted_runs

    for run_id, age in (("run-stale", 600), ("run-live", 5)):
        _paused(run_id, "reject", expired=False)
        _sql("UPDATE agent_runs SET status = 'running', pending_gate = NULL, updated_at = ? WHERE run_id = ?",
             ((NOW() - timedelta(seconds=age)).isoformat(), run_id))
    assert mark_interrupted_runs() == 1
    assert _run("run-stale")["status"] == "interrupted"
    assert _run("run-live")["status"] == "running", "another replica's live run is left alone"
