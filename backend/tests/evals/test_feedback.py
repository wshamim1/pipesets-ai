"""Feedback on runs (plan.md F2): builders rate in the runner, chat-link visitors with the sealed token
from the answer's done event, API callers through /v1; ratings replace each other per rater, are
counted per version, stay inside their tenant and become eval cases. The tests are steps of one
scenario, in order."""
import json

import pytest

from helpers import hdr, mock_flow

ADMIN = hdr()
state = {}


def events(r):
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


@pytest.fixture(scope="module")
def app_id(client):
    aid = client.post("/api/apps", json={"name": "Lease bot", "flow_data": mock_flow("fb")}, headers=ADMIN).json()["id"]
    assert client.post(f"/api/apps/{aid}/publish", headers=ADMIN).status_code == 200
    return aid


@pytest.fixture(scope="module")
def api_key(client):
    r = client.post("/api/api-keys", json={"name": "fb", "scopes": ["apps:read", "apps:run"]}, headers=ADMIN)
    assert r.status_code in (200, 201), r.text
    return r.json()["key"]


def v1_run(client, key, app_id, prompt):
    r = client.post(f"/v1/apps/{app_id}/run", json={"prompt": prompt, "stream": False},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


def test_api_caller_rates_a_run(client, app_id, api_key):
    run_id = v1_run(client, api_key, app_id, "When does the lease end?")
    state["api_run"] = run_id
    auth = {"Authorization": f"Bearer {api_key}"}
    r = client.post(f"/v1/runs/{run_id}/feedback", json={"rating": -1, "comment": "wrong date", "user": "u1"}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["rating"] == -1
    # Rating again (same end user) replaces it; another end user adds a second rating
    client.post(f"/v1/runs/{run_id}/feedback", json={"rating": 1, "user": "u1"}, headers=auth)
    client.post(f"/v1/runs/{run_id}/feedback", json={"rating": -1, "user": "u2", "correction": "2031-06-30"}, headers=auth)
    items = client.get("/api/feedback", params={"app_id": app_id}, headers=ADMIN).json()["items"]
    assert sorted((i["rater"], i["rating"]) for i in items) == [("u1", 1), ("u2", -1)]
    assert all(i["prompt"] == "When does the lease end?" and i["output"] for i in items)
    assert all(i["app_version"] == 1 and i["source"] == "api" for i in items)


def test_bad_ratings_and_unknown_runs_are_refused(client, api_key):
    auth = {"Authorization": f"Bearer {api_key}"}
    assert client.post(f"/v1/runs/{state['api_run']}/feedback", json={"rating": 5}, headers=auth).status_code == 422
    assert client.post("/v1/runs/nope/feedback", json={"rating": 1}, headers=auth).status_code == 404


def test_builder_rates_in_the_runner(client):
    run_id = state["api_run"]
    assert client.get(f"/api/feedback/runs/{run_id}", headers=ADMIN).json() is None
    r = client.put(f"/api/feedback/runs/{run_id}", json={"rating": 1, "comment": "fine"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["source"] == "runner"
    assert client.get(f"/api/feedback/runs/{run_id}", headers=ADMIN).json()["rating"] == 1
    assert client.delete(f"/api/feedback/runs/{run_id}", headers=ADMIN).status_code == 200
    assert client.get(f"/api/feedback/runs/{run_id}", headers=ADMIN).json() is None


def test_chat_visitor_rates_with_the_done_token(client, app_id):
    link = client.post("/api/chat-links", json={"app_id": app_id}, headers=ADMIN).json()
    token = link["token"]
    session = client.post(f"/v1/chat/{token}/session", json={}).json()["session"]
    evs = events(client.post(f"/v1/chat/{token}/message", json={"session": session, "message": "Rent?"}))
    done = [e for e in evs if e["type"] == "done"][-1]
    assert done["feedback"] and not any("run_id" in e for e in evs)   # visitors still never see run ids
    body = {"session": session, "feedback": done["feedback"], "rating": -1, "comment": "no rent amount"}
    assert client.post(f"/v1/chat/{token}/feedback", json=body).status_code == 200
    # Another visitor's session can't use this answer's token
    other = client.post(f"/v1/chat/{token}/session", json={}).json()["session"]
    assert client.post(f"/v1/chat/{token}/feedback", json={**body, "session": other}).status_code == 404
    assert client.post(f"/v1/chat/{token}/feedback", json={**body, "feedback": "forged"}).status_code == 404
    items = client.get("/api/feedback", params={"source": "chat_link"}, headers=ADMIN).json()["items"]
    assert len(items) == 1 and items[0]["rater"] == "chat visitor" and items[0]["prompt"] == "Rent?"
    state["chat_feedback"] = items[0]["id"]


def test_summary_per_version(client, app_id):
    rows = client.get("/api/feedback/summary", params={"app_id": app_id}, headers=ADMIN).json()
    assert rows == [{**rows[0], "app_id": app_id, "version": 1, "up": 1, "down": 2, "total": 3,
                     "satisfaction": round(1 / 3, 4)}]
    down = client.get("/api/feedback", params={"rating": -1}, headers=ADMIN).json()
    assert down["total"] == 2


def test_other_tenants_see_nothing(client, app_id, api_key):
    tid = client.post("/api/iam/tenants", json={"name": "Other"}, headers=ADMIN).json()["id"]
    pid = client.post("/api/iam/projects", json={"name": "P"}, headers=hdr(tenant=tid)).json()["id"]
    other = hdr(tenant=tid, project=pid)
    assert client.get("/api/feedback", headers=other).json()["total"] == 0
    assert client.get("/api/feedback/summary", headers=other).json() == []
    assert client.put(f"/api/feedback/runs/{state['api_run']}", json={"rating": 1}, headers=other).status_code == 404


def test_ratings_become_eval_cases(client):
    ids = [i["id"] for i in client.get("/api/feedback", headers=ADMIN).json()["items"]]
    r = client.post("/api/feedback/export", json={"feedback_ids": ids, "dataset_name": "From users"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["exported"] == 3
    cases = client.get(f"/api/eval/datasets/{out['dataset_id']}/cases", headers=ADMIN).json()
    # Same prompt twice (two API raters) is one case: the first one wins, duplicates are skipped
    assert out["cases_created"] == 2 and out["skipped_duplicates"] == 1
    by_prompt = {c["prompt"]: c for c in cases}
    assert "feedback" in by_prompt["Rent?"]["tags"] and "thumbs_down" in by_prompt["Rent?"]["tags"]
    assert by_prompt["Rent?"]["expected_output"] == ""   # 👎 without a correction: left for someone to fill in
    items = client.get("/api/feedback", headers=ADMIN).json()["items"]
    assert all(i["dataset_id"] == out["dataset_id"] for i in items)
