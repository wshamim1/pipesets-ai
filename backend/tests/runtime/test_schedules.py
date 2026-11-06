"""Scheduled pipeline runs: API validation, execution, claiming and auto-pause. The scheduler's
polling loop never starts (the TestClient isn't used as a context manager); runs are jobs,
worked with helpers.run_jobs."""
import pytest

from db import get_db_connection
from helpers import mock_flow, run_jobs, run_row
from services import scheduler


def raw(schedule_id):
    conn = get_db_connection()
    try:
        return dict(conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone())
    finally:
        conn.close()


def set_due(schedule_id):
    conn = get_db_connection()
    conn.execute("UPDATE schedules SET next_run_at = '2000-01-01T00:00:00Z' WHERE id = ?", (schedule_id,))
    conn.commit()
    conn.close()


def run_once(schedule_id):
    """Fire the schedule now, work the queue, return the run row."""
    run_row_id = scheduler.launch(raw(schedule_id), "manual")
    run_jobs()
    return run_row("schedule_runs", run_row_id)


@pytest.fixture(scope="module")
def aid(client):
    return client.post("/api/apps", json={"name": "Nightly", "description": "", "flow_data": mock_flow("v1")}).json()["id"]


@pytest.fixture(scope="module")
def body(aid):
    return {"app_id": aid, "cron": "0 2 * * *", "timezone": "UTC", "prompt": "Summarize yesterday."}


@pytest.fixture(scope="module")
def sid(client, aid, body):
    assert client.post("/api/schedules", json=body).status_code == 409, "unpublished pipeline refused"
    client.post(f"/api/apps/{aid}/publish")
    r = client.post("/api/schedules", json=body)
    assert r.status_code == 201
    return r.json()["id"]


def test_cron_preview(client):
    r = client.post("/api/schedules/preview", json={"cron": "0 9 * * 1-5", "timezone": "Europe/London"})
    assert r.status_code == 200 and len(r.json()["next_runs"]) == 5
    assert r.json()["next_runs"][0].endswith("Z")
    for bad in ({"cron": "every day"}, {"cron": "0 0 9 * * *"}, {"cron": "* * * * *"},
                {"cron": "0 9 * * *", "timezone": "Mars/Base"}):
        assert client.post("/api/schedules/preview", json=bad).status_code == 422, bad


def test_create(client, aid, body, sid):
    s = next(x for x in client.get(f"/api/schedules?app_id={aid}").json() if x["id"] == sid)
    assert s["name"] == "Nightly schedule"
    assert s["next_run_at"] and s["next_run_at"].endswith("Z")
    assert s["app_name"] == "Nightly" and s["app_version"] == 1
    assert client.post("/api/schedules", json={**body, "app_id": "nope"}).status_code == 404
    assert [x["id"] for x in client.get(f"/api/schedules?app_id={aid}").json()] == [sid]
    assert client.get("/api/schedules?app_id=other").json() == []


def test_runs_latest_published_version(client, aid, sid):
    client.post(f"/api/apps/{aid}/edit")
    client.put(f"/api/apps/{aid}", json={"name": "Nightly", "description": "", "flow_data": {"nodes": [], "edges": []}})
    res = run_once(sid)
    assert res["status"] == "completed" and res["output_preview"], "runs while a draft is open"
    assert res["attempts"] == 1 and res["job_id"]
    runs = client.get(f"/api/schedules/{sid}/runs").json()
    assert len(runs) == 1 and runs[0]["status"] == "completed" and runs[0]["app_version"] == 1
    assert runs[0]["cost_usd"] == 0.0
    assert raw(sid)["last_status"] == "completed"


def test_claiming(client, sid):
    set_due(sid)
    first = scheduler._claim_due()
    second = scheduler._claim_due()
    assert [x[0]["id"] for x in first] == [sid] and second == [], "a due schedule fires exactly once"
    assert raw(sid)["next_run_at"] > "2000-01-01T00:00:00Z"
    client.patch(f"/api/schedules/{sid}", json={"enabled": False})
    set_due(sid)
    assert scheduler._claim_due() == [], "disabled schedules aren't claimed"


def test_update(client, sid):
    r = client.patch(f"/api/schedules/{sid}", json={"enabled": True, "cron": "30 6 * * 1"})
    assert r.status_code == 200 and r.json()["enabled"] and r.json()["cron"] == "30 6 * * 1"
    assert r.json()["next_run_at"] != "2000-01-01T00:00:00Z"
    assert client.patch(f"/api/schedules/{sid}", json={"cron": "nope"}).status_code == 422
    assert client.patch(f"/api/schedules/{sid}", json={"enabled": False}).json()["next_run_at"] is None


def test_auto_pause_and_delete(client, aid, body):
    bad = client.post("/api/apps", json={"name": "No LLM", "description": "", "flow_data": {
        "nodes": [{"id": "t", "type": "start", "data": {}}], "edges": []}}).json()
    client.post(f"/api/apps/{bad['id']}/publish")
    bs = client.post("/api/schedules", json={**body, "app_id": bad["id"], "max_failures": 2}).json()
    run_once(bs["id"])
    assert raw(bs["id"])["enabled"] == 1 and raw(bs["id"])["consecutive_failures"] == 1
    run_once(bs["id"])
    paused = raw(bs["id"])
    assert paused["enabled"] == 0 and paused["next_run_at"] is None
    assert "Paused after 2" in (paused["last_error"] or "")
    assert client.patch(f"/api/schedules/{bs['id']}", json={"enabled": True}).json()["consecutive_failures"] == 0

    assert client.delete(f"/api/schedules/{bs['id']}").json()["deleted"]
    assert client.get(f"/api/schedules/{bs['id']}/runs").status_code == 404
    client.delete(f"/api/apps/{aid}")
    assert client.get(f"/api/schedules?app_id={aid}").json() == [], "deleting the pipeline removes its schedules"
