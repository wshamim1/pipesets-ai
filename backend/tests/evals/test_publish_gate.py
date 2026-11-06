"""Eval-gated publishing: gate config, pass / block / force / warn, regression against the live
version, dry runs and gates that can't run. The pipeline uses the mock provider, whose answer
echoes the prompt — so a case passes the "contains" scorer when its expected output appears in
its prompt. The tests are steps of one scenario on one pipeline, in order."""
import pytest

from helpers import mock_flow
from services import publish_gate


@pytest.fixture(scope="module")
def api(client):
    class Api:
        def add_case(self, ds_id, prompt, expected):
            r = client.post(f"/api/eval/datasets/{ds_id}/cases", json={"prompt": prompt, "expected_output": expected})
            assert r.status_code in (200, 201), r.text

        def publish(self, aid, **body):
            client.post(f"/api/apps/{aid}/edit")
            return client.post(f"/api/apps/{aid}/publish", json=body or None)

        def version(self, aid):
            return client.get(f"/api/apps/{aid}").json()["version"]

        def set_gate(self, aid, **body):
            return client.put(f"/api/apps/{aid}/publish-gate", json=body)
    return Api()


@pytest.fixture(scope="module")
def aid(client):
    return client.post("/api/apps", json={"name": "Support bot", "description": "", "flow_data": mock_flow("v1")}).json()["id"]


@pytest.fixture(scope="module")
def ds_id(client, aid, api):
    ds_id = client.post("/api/eval/datasets", json={"name": "Support regression", "app_id": aid}).json()["id"]
    for i in range(4):
        api.add_case(ds_id, f"How do I reset my password? case {i}", "password")
    return ds_id


@pytest.fixture(scope="module")
def gate_body(ds_id):
    return {"dataset_id": ds_id, "min_pass_rate": 0.75}


def test_judge_rules():
    gate = {"min_pass_rate": 0.8, "no_regression": True, "regression_tolerance": 0.05, "mode": "block",
            "dataset_id": "d", "scorer": "contains"}
    run = {"id": "r", "total": 10, "passed": 8}
    base = {"version": 3, "pass_rate": 0.9, "eval_run_id": "x"}
    assert publish_gate.judge(gate, run, None)["status"] == "passed", "at threshold"
    assert publish_gate.judge(gate, {**run, "passed": 7}, None)["reasons"][0].startswith("Pass rate 70% is below")
    assert publish_gate.judge(gate, {**run, "passed": 9}, {**base, "pass_rate": 0.92})["status"] == "passed"
    r = publish_gate.judge(gate, run, base)
    assert r["status"] == "failed" and "regressed from v3's 90%" in r["reasons"][0]
    assert publish_gate.judge({**gate, "no_regression": False}, run, base)["status"] == "passed"


def test_publish_without_gate(client, aid):
    r = client.post(f"/api/apps/{aid}/publish")
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["publish_gate"] is None
    assert client.get(f"/api/apps/{aid}/publish-gate").json() is None


def test_gate_config(api, aid, gate_body):
    assert api.set_gate(aid, **gate_body, scorer="vibes").status_code == 422
    assert api.set_gate(aid, **gate_body, mode="maybe").status_code == 422
    assert api.set_gate(aid, **{**gate_body, "min_pass_rate": 1.5}).status_code == 422
    assert api.set_gate(aid, **{**gate_body, "dataset_id": "nope"}).status_code == 404
    assert api.set_gate("nope", **gate_body).status_code == 404
    g = api.set_gate(aid, **gate_body).json()
    assert g["mode"] == "block" and g["no_regression"] and g["scorer"] == "contains", "defaults"
    assert g["dataset_name"] == "Support regression" and g["case_count"] == 4
    assert api.set_gate(aid, **gate_body).json()["min_pass_rate"] == 0.75, "update is an upsert"


def test_passing_gate(client, api, aid):
    r = api.publish(aid)
    gr = r.json()["publish_gate"]
    assert r.status_code == 200 and r.json()["version"] == 2
    assert gr["status"] == "passed" and gr["pass_rate"] == 1.0 and gr["total"] == 4
    assert gr["baseline"] is None, "first gated publish: v1 has no run to compare with"
    runs = client.get(f"/api/eval/runs?app_id={aid}").json()
    assert runs[0]["id"] == gr["eval_run_id"] and runs[0]["app_version"] == 2
    vers = client.get(f"/api/apps/{aid}/versions").json()
    assert vers[0]["version"] == 2 and vers[0]["gate_status"] == "passed"
    assert vers[0]["gate_pass_rate"] == 1.0 and vers[0]["published_by"]
    assert vers[1]["gate_status"] is None


def test_failing_gate_blocks(client, api, aid, ds_id):
    api.add_case(ds_id, "Cancel my plan", "zzz-never")
    api.add_case(ds_id, "Where is my invoice", "zzz-never")   # 4/6 = 67%
    r = api.publish(aid)
    assert r.status_code == 409 and api.version(aid) == 2
    reasons = r.json()["detail"]["gate"]["reasons"]
    assert any("below the required 75%" in x for x in reasons)
    assert any("regressed from v2's 100%" in x for x in reasons)
    assert client.get(f"/api/eval/runs?app_id={aid}").json()[0]["app_version"] == 0, "stays a draft run"

    r = client.post(f"/api/apps/{aid}/publish-gate/check", json={})
    assert r.status_code == 200 and r.json()["status"] == "failed" and r.json()["passed"] == 4
    assert api.version(aid) == 2, "a dry run doesn't publish"


def test_force(client, api, aid):
    r = api.publish(aid, force=True)
    assert r.status_code == 200 and r.json()["version"] == 3 and r.json()["publish_gate"]["status"] == "overridden"
    assert client.get(f"/api/apps/{aid}/versions").json()[0]["gate_status"] == "overridden"


def test_warn_mode_and_moving_baseline(api, aid, ds_id, gate_body):
    api.set_gate(aid, **{**gate_body, "min_pass_rate": 0.5, "mode": "warn"})
    gr = api.publish(aid).json()["publish_gate"]
    assert gr["status"] == "passed" and gr["baseline"]["version"] == 3, "same score as live passes"
    api.add_case(ds_id, "Talk to a human", "zzz-never")      # 4/7 = 57%
    r = api.publish(aid)
    gr = r.json()["publish_gate"]
    assert r.status_code == 200 and r.json()["version"] == 5 and gr["status"] == "warned"
    assert any("regressed from v4's 67%" in x for x in gr["reasons"])
    api.set_gate(aid, **{**gate_body, "min_pass_rate": 0.5, "regression_tolerance": 0.2})
    assert api.publish(aid).json()["publish_gate"]["status"] == "passed", "within tolerance"


def test_gates_that_cant_run(client, api, aid, ds_id, gate_body):
    api.set_gate(aid, **gate_body, enabled=False)
    r = api.publish(aid)
    assert r.status_code == 200 and r.json()["publish_gate"] is None, "disabled gate skipped"

    api.set_gate(aid, **gate_body)
    client.delete(f"/api/eval/datasets/{ds_id}")
    r = api.publish(aid)
    assert r.status_code == 409 and "could not run" in r.json()["detail"]["message"]
    assert r.json()["detail"]["gate"]["status"] == "error"

    empty = client.post("/api/eval/datasets", json={"name": "Empty", "app_id": aid}).json()
    api.set_gate(aid, **{**gate_body, "dataset_id": empty["id"]})
    r = api.publish(aid)
    assert r.status_code == 409 and "has no cases" in r.json()["detail"]["message"]


def test_remove_gate(client, api, aid, gate_body):
    assert client.delete(f"/api/apps/{aid}/publish-gate").json()["deleted"]
    assert api.publish(aid).status_code == 200
    assert client.post(f"/api/apps/{aid}/publish-gate/check").status_code == 404
    empty = client.post("/api/eval/datasets", json={"name": "Empty 2", "app_id": aid}).json()
    api.set_gate(aid, **{**gate_body, "dataset_id": empty["id"]})
    client.delete(f"/api/apps/{aid}")
    assert publish_gate.get_gate(aid, "tenant_demo", "proj_research") is None, "deleting the pipeline removes its gate"
