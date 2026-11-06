"""Published-version snapshots and version pinning for pipeline children."""
import pytest

from helpers import mock_flow
from services.pipeline_runner import RunScope, _load_published_app


def flow(tag):
    return {"nodes": [{"id": tag, "type": "llm", "data": {"label": tag}}], "edges": []}


@pytest.fixture(scope="module")
def child(client):
    """A pipeline published as v1 (node "one") and v2 (node "two")."""
    app = client.post("/api/apps", json={"name": "Child", "description": "d", "flow_data": flow("one")}).json()
    aid = app["id"]
    assert client.post(f"/api/apps/{aid}/publish").json()["version"] == 1
    client.post(f"/api/apps/{aid}/edit")
    client.put(f"/api/apps/{aid}", json={"name": "Child", "description": "d", "flow_data": flow("two")})
    assert client.post(f"/api/apps/{aid}/publish").json()["version"] == 2
    return app


def test_versions_listing_and_detail(client, child):
    aid = child["id"]
    versions = client.get(f"/api/apps/{aid}/versions").json()
    assert [v["version"] for v in versions] == [2, 1], "newest first"
    assert versions[0]["node_count"] == 1
    assert client.get(f"/api/apps/{aid}/versions/1").json()["flow_data"]["nodes"][0]["id"] == "one"
    assert client.get(f"/api/apps/{aid}/versions/9").status_code == 404


def test_pinned_versions(client, child):
    aid = child["id"]
    scope = RunScope(tenant_id=child["tenant_id"], project_id=child["project_id"], user_id=child["owner_user_id"])
    assert _load_published_app(aid, scope, 1)["flow"]["nodes"][0]["id"] == "one"
    assert _load_published_app(aid, scope, 2)["flow"]["nodes"][0]["id"] == "two"
    assert _load_published_app(aid, scope)["version"] == 2, "version 0 runs the current one"

    # A draft in progress must not affect pinned children
    client.post(f"/api/apps/{aid}/edit")
    client.put(f"/api/apps/{aid}", json={"name": "Child", "description": "d", "flow_data": flow("draft")})
    assert _load_published_app(aid, scope, 2)["flow"]["nodes"][0]["id"] == "two"
    with pytest.raises(LookupError):
        _load_published_app(aid, scope, 9)


def test_pipeline_only_canvas(client):
    """Start → Pipeline (pinned) → Stop, with no LLM of its own, runs the called pipeline."""
    llm_app = client.post("/api/apps", json={"name": "Mocky", "description": "", "flow_data": mock_flow("l1", "LLM")}).json()
    client.post(f"/api/apps/{llm_app['id']}/publish")
    canvas = {"nodes": [
        {"id": "s", "type": "start", "data": {}},
        {"id": "p", "type": "child_agent", "data": {"kind": "pipeline", "app_id": llm_app["id"], "app_version": 1}},
        {"id": "e", "type": "stop", "data": {}},
    ], "edges": [{"source": "s", "target": "p"}, {"source": "p", "target": "e"}]}
    r = client.post("/api/pipelines/run-flow", json={"prompt": "hello", "flow_data": canvas}).json()
    assert r["ok"] and r["output"]
    assert r["model"].endswith("v1"), "used the pinned version"
    summary = client.post("/api/pipelines/summary", json={"flow_data": canvas}).json()
    assert [m["model"] for m in summary["models"]] == ["mock-gpt-4"]
    assert [(p["name"], p["version"]) for p in summary["pipelines"]] == [("Mocky", 1)]
    assert summary["models"][0]["sources"] == ["Mocky v1"]

    canvas["nodes"][1]["data"]["app_version"] = 7
    r = client.post("/api/pipelines/run-flow", json={"prompt": "hello", "flow_data": canvas}).json()
    assert not r["ok"] and "v7" in r["error"]
    summary = client.post("/api/pipelines/summary", json={"flow_data": canvas}).json()
    assert summary["pipelines"] == [] and "v7" in summary["errors"][0]


def test_versions_removed_with_app(client, child):
    client.delete(f"/api/apps/{child['id']}")
    assert client.get(f"/api/apps/{child['id']}/versions").json() == []
