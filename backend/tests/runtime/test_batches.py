"""Batch runs (plan.md F5): reading input files, one prompt per row from a template, at most
``concurrency`` rows of a batch queued at once, every row accounted for, cancel, retry, a lost
queue chain picked up by the sweep, CSV export and tenant scoping. The tests are steps of one
scenario, in order."""
import asyncio
import csv
import io

import pytest

from db import get_db_connection
from helpers import hdr, mock_flow, run_jobs
from services import batches

ADMIN = hdr()
ROWS = [{"tenant": f"Tenant {i}", "unit": str(100 + i)} for i in range(6)] + [{"tenant": "", "unit": ""}]
TEMPLATE = "Summarise the lease for {tenant} in unit {unit}"
state = {}


def statuses(batch_id):
    conn = get_db_connection()
    try:
        return [r["status"] for r in conn.execute("SELECT status FROM batch_items WHERE batch_id = ? ORDER BY idx",
                                                  (batch_id,)).fetchall()]
    finally:
        conn.close()


@pytest.fixture(scope="module")
def app_id(client):
    return client.post("/api/apps", json={"name": "Abstractor", "flow_data": mock_flow("ab")}, headers=ADMIN).json()["id"]


def upload(client, name, content):
    return client.post("/api/batches/parse", files={"file": (name, content)}, headers=ADMIN)


def test_input_files_are_read_into_rows(client):
    r = upload(client, "leases.csv", b"\xef\xbb\xbftenant,unit\nAcme,101\n,\nBeta,102\n")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["tenant", "unit"] and body["total"] == 2 and body["prompt_template"] == ""
    assert body["rows"][1] == {"tenant": "Beta", "unit": "102"}
    r = upload(client, "q.jsonl", b'{"prompt": "a"}\n{"prompt": "b", "extra": 1}\n').json()
    assert r["columns"] == ["prompt", "extra"] and r["prompt_template"] == "{prompt}"
    r = upload(client, "q.txt", b"first\n\nsecond\n").json()
    assert r["rows"] == [{"prompt": "first"}, {"prompt": "second"}]
    assert upload(client, "q.pdf", b"%PDF").status_code == 415
    assert upload(client, "bad.jsonl", b"{nope\n").status_code == 422


def test_templates():
    assert batches.render(TEMPLATE, {"tenant": "Acme", "unit": 7}) == "Summarise the lease for Acme in unit 7"
    assert batches.placeholders("{a} and { b }") == ["a", "b"]
    assert batches.default_template(["only"]) == "{only}"


def test_only_published_pipelines_and_known_columns(client, app_id):
    body = {"app_id": app_id, "rows": ROWS, "prompt_template": TEMPLATE}
    assert client.post("/api/batches", json=body, headers=ADMIN).status_code == 409
    assert client.post(f"/api/apps/{app_id}/publish", headers=ADMIN).status_code == 200
    r = client.post("/api/batches", json={**body, "prompt_template": "Hi {tenant} {floor}"}, headers=ADMIN)
    assert r.status_code == 422 and "floor" in r.json()["detail"]
    r = client.post("/api/batches", json={**body, "prompt_template": ""}, headers=ADMIN)
    assert r.status_code == 422   # two columns and no template: nothing to guess from


def test_a_batch_queues_only_its_concurrency(client, app_id):
    r = client.post("/api/batches", json={"app_id": app_id, "rows": ROWS, "prompt_template": TEMPLATE,
                                          "concurrency": 2, "name": "Q3 leases"}, headers=ADMIN)
    assert r.status_code == 201, r.text
    batch = r.json()
    state["batch"] = batch["id"]
    assert batch["status"] == "running" and batch["total"] == 7 and batch["name"] == "Q3 leases"
    # Two queued, the rest wait; the empty row fails up front without a run
    assert statuses(batch["id"]) == ["queued", "queued", "pending", "pending", "pending", "pending", "failed"]


def test_every_row_runs_and_the_batch_finishes(client):
    run_jobs()
    batch = client.get(f"/api/batches/{state['batch']}", headers=ADMIN).json()
    assert batch["status"] == "done" and batch["finished"] == 7
    assert batch["counts"]["completed"] == 6 and batch["counts"]["failed"] == 1
    items = client.get(f"/api/batches/{state['batch']}/items", headers=ADMIN).json()["items"]
    assert items[0]["prompt"] == "Summarise the lease for Tenant 0 in unit 100"
    assert all(i["output"] and i["run_id"] and i["version"] == 1 for i in items[:6])
    assert items[6]["error"] == "The prompt for this row is empty"
    # Each row's run is a normal checkpointed run: it opens in the trace drawer and can be rated
    conn = get_db_connection()
    try:
        assert conn.execute("SELECT goal FROM agent_runs WHERE run_id = ?", (items[0]["run_id"],)).fetchone()["goal"] \
            == items[0]["prompt"]
    finally:
        conn.close()
    failed = client.get(f"/api/batches/{state['batch']}/items", params={"status": "failed"}, headers=ADMIN).json()
    assert failed["total"] == 1


def test_results_download_as_csv(client):
    r = client.get(f"/api/batches/{state['batch']}/export", headers=ADMIN)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert list(rows[0]) == ["tenant", "unit", "output", "status", "error", "cost_usd", "latency_ms", "run_id"]
    assert rows[0]["tenant"] == "Tenant 0" and rows[0]["status"] == "completed" and rows[0]["output"]


def test_rows_with_no_prompt_are_not_retried(client):
    assert client.post(f"/api/batches/{state['batch']}/retry", headers=ADMIN).status_code == 409


def test_cancel_then_retry(client, app_id):
    batch = client.post("/api/batches", json={"app_id": app_id, "rows": ROWS[:5], "prompt_template": TEMPLATE},
                        headers=ADMIN).json()
    assert client.delete(f"/api/batches/{batch['id']}", headers=ADMIN).status_code == 409   # still running
    r = client.post(f"/api/batches/{batch['id']}/cancel", headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert statuses(batch["id"]) == ["cancelled"] * 5
    run_jobs()   # the cancelled jobs are dead: nothing runs
    assert statuses(batch["id"]) == ["cancelled"] * 5
    assert client.post(f"/api/batches/{batch['id']}/cancel", headers=ADMIN).status_code == 404
    r = client.post(f"/api/batches/{batch['id']}/retry", headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "running"
    run_jobs()
    assert statuses(batch["id"]) == ["completed"] * 5
    assert client.get(f"/api/batches/{batch['id']}", headers=ADMIN).json()["status"] == "done"
    assert client.delete(f"/api/batches/{batch['id']}", headers=ADMIN).status_code == 200
    assert client.get(f"/api/batches/{batch['id']}", headers=ADMIN).status_code == 404


def test_a_lost_queue_chain_is_picked_up_by_the_sweep(client, app_id):
    batch = client.post("/api/batches", json={"app_id": app_id, "rows": ROWS[:4], "prompt_template": TEMPLATE,
                                              "concurrency": 1}, headers=ADMIN).json()
    # As if a worker died after taking the job and before queueing the next row: the job is gone,
    # the row is back to pending and nothing is queued
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM jobs WHERE dedupe_key = ?", (batches.dedupe_key(batch["id"]),))
        conn.execute("UPDATE batch_items SET status = 'pending', job_id = NULL WHERE batch_id = ?", (batch["id"],))
        conn.commit()
    finally:
        conn.close()
    run_jobs()
    assert statuses(batch["id"]) == ["pending"] * 4
    asyncio.run(batches._sweep())
    run_jobs()
    assert statuses(batch["id"]) == ["completed"] * 4


def test_other_tenants_see_nothing(client):
    tid = client.post("/api/iam/tenants", json={"name": "Other"}, headers=ADMIN).json()["id"]
    pid = client.post("/api/iam/projects", json={"name": "P"}, headers=hdr(tenant=tid)).json()["id"]
    other = hdr(tenant=tid, project=pid)
    assert client.get("/api/batches", headers=other).json() == []
    for path in ("", "/items", "/export"):
        assert client.get(f"/api/batches/{state['batch']}{path}", headers=other).status_code == 404
    assert client.post(f"/api/batches/{state['batch']}/retry", headers=other).status_code == 404
    assert len(client.get("/api/batches", headers=ADMIN).json()) == 2
