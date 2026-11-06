"""Traces and evals are scoped to their tenant + project: another tenant can't list, read, export,
change or delete them (these tables used to be shared by every workspace)."""
from datetime import datetime

import pytest

from db import get_db_connection
from helpers import mock_flow
from routers.traces import write_trace
from services.secret_store import request_scope


@pytest.fixture(scope="module", autouse=True)
def _setup(env):
    env.setenv("AUTH_MODE", "session")


def signup(client, email):
    data = client.post("/api/auth/signup", json={"email": email, "password": "password123",
                                                 "display_name": email.split("@")[0]}).json()
    t = data["tenants"][0]
    return {"Authorization": f"Bearer {data['token']}", "x-tenant-id": t["id"], "x-project-id": t["projects"][0]["id"]}


def scope_of(h):
    return h["x-tenant-id"], h["x-project-id"]


@pytest.fixture(scope="module")
def A(client):
    return signup(client, "trace-owner@example.com")


@pytest.fixture(scope="module")
def B(client):
    return signup(client, "trace-other@example.com")


@pytest.fixture(scope="module")
def trace_run(A):
    token = request_scope.set(scope_of(A))
    try:
        write_trace(run_id="run-scoped-A", provider="mock", model="m", cost_usd=0.5, prompt_preview="A-SECRET")
    finally:
        request_scope.reset(token)
    return "run-scoped-A"


def test_traces_are_only_listed_for_their_scope(client, A, B, trace_run):
    assert trace_run in [t["run_id"] for t in client.get("/api/traces", headers=A).json()]
    assert trace_run not in [t["run_id"] for t in client.get("/api/traces", headers=B).json()]
    assert client.get(f"/api/traces/{trace_run}", headers=A).json()[0]["prompt_preview"] == "A-SECRET"
    assert client.get(f"/api/traces/{trace_run}", headers=B).json() == []


def test_cost_summary_counts_only_the_callers_traces(client, A, B, trace_run):
    assert client.get("/api/traces/cost-summary", headers=A).json()["totals"]["total_cost"] >= 0.5
    assert not client.get("/api/traces/cost-summary", headers=B).json()["totals"]["total_cost"]


def test_clearing_traces_leaves_other_tenants_alone(client, A, B, trace_run):
    assert client.delete("/api/traces", headers=B).status_code == 200
    assert trace_run in [t["run_id"] for t in client.get("/api/traces", headers=A).json()]


def test_a_trace_written_outside_a_request_takes_its_apps_scope(client, A, B):
    app_id = client.post("/api/apps", json={"name": "Scoped", "flow_data": mock_flow()}, headers=A).json()["id"]
    write_trace(run_id="run-app-scoped", app_id=app_id, provider="mock", model="m")
    assert "run-app-scoped" in [t["run_id"] for t in client.get("/api/traces", headers=A).json()]
    assert "run-app-scoped" not in [t["run_id"] for t in client.get("/api/traces", headers=B).json()]


@pytest.fixture(scope="module")
def dataset(client, A):
    ds = client.post("/api/eval/datasets", json={"name": "A-only"}, headers=A).json()
    case = client.post(f"/api/eval/datasets/{ds['id']}/cases", json={"prompt": "A-SECRET-PROMPT"}, headers=A).json()
    return ds["id"], case["id"]


def test_datasets_are_only_listed_for_their_scope(client, A, B, dataset):
    ds_id, _ = dataset
    assert ds_id in [d["id"] for d in client.get("/api/eval/datasets", headers=A).json()]
    assert ds_id not in [d["id"] for d in client.get("/api/eval/datasets", headers=B).json()]


def test_other_tenant_cannot_read_change_or_delete_a_dataset(client, A, B, dataset):
    ds_id, case_id = dataset
    assert client.get(f"/api/eval/datasets/{ds_id}/cases", headers=B).status_code == 404
    assert client.get(f"/api/eval/datasets/{ds_id}/export?format=csv", headers=B).status_code == 404
    assert client.patch(f"/api/eval/datasets/{ds_id}", json={"name": "taken"}, headers=B).status_code == 404
    assert client.post(f"/api/eval/datasets/{ds_id}/cases", json={"prompt": "x"}, headers=B).status_code == 404
    assert client.post(f"/api/eval/datasets/{ds_id}/cases/bulk",
                       json={"cases": [{"prompt": "x"}]}, headers=B).status_code == 404
    assert client.put(f"/api/eval/cases/{case_id}", json={"prompt": "x"}, headers=B).status_code == 404
    assert client.delete(f"/api/eval/cases/{case_id}", headers=B).status_code == 404
    assert client.delete(f"/api/eval/datasets/{ds_id}", headers=B).status_code == 404
    cases = client.get(f"/api/eval/datasets/{ds_id}/cases", headers=A).json()
    assert [c["prompt"] for c in cases] == ["A-SECRET-PROMPT"]


def test_eval_runs_are_scoped(client, A, B, dataset):
    ds_id, _ = dataset
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO eval_runs (id, tenant_id, project_id, app_id, dataset_id, dataset_name, created_at) "
                     "VALUES (?,?,?,?,?,?,?)", ("evr-A", *scope_of(A), "app-x", ds_id, "A-only",
                                                datetime.utcnow().isoformat()))
        conn.commit()
    finally:
        conn.close()
    assert "evr-A" in [r["id"] for r in client.get("/api/eval/runs", headers=A).json()]
    assert "evr-A" not in [r["id"] for r in client.get("/api/eval/runs", headers=B).json()]
    assert client.get("/api/eval/runs/evr-A/results", headers=B).status_code == 404
    assert client.get("/api/eval/runs/evr-A/export?format=csv", headers=B).status_code == 404
    assert client.delete("/api/eval/runs/evr-A", headers=B).status_code == 404
    assert client.get("/api/eval/runs/evr-A/results", headers=A).status_code == 200
