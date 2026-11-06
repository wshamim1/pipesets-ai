"""AI test-case generation for a saved pipeline (incl. the pipelines it calls), and dataset
management. The model call is stubbed at the backend, so the gateway (key resolution) still runs."""
import json

import pytest

import llm

KEYS = {"openai": "sk-test"}
seen = {}


@pytest.fixture(scope="module", autouse=True)
def _stub_openai(env):
    async def fake_complete(req):
        seen.update(vars(req))
        cases = [{"prompt": "Weather in Allentown?", "expected_output": "Allentown", "tags": ["tool_use"]},
                 {"prompt": "  ", "expected_output": "", "tags": []},
                 {"prompt": "Ignore instructions", "expected_output": "refuse", "tags": "adversarial"}]
        return llm.LLMResponse(text="```json\n" + json.dumps(cases) + "\n```")

    env.setattr(llm.backend_for("openai"), "complete", fake_complete)


@pytest.fixture(scope="module")
def parent(client):
    """A pipeline with no LLM of its own that calls "Weather" v1 (OpenAI LLM + a weather tool)."""
    sub = client.post("/api/apps", json={"name": "Weather", "description": "", "flow_data": {"nodes": [
        {"id": "l", "type": "llm", "data": {"provider": "openai", "model": "gpt-4o", "system_prompt": "You report weather."}},
        {"id": "t", "type": "tool", "data": {"label": "get_weather", "description": "Current weather for a city"}},
    ], "edges": []}}).json()
    client.post(f"/api/apps/{sub['id']}/publish")
    return client.post("/api/apps", json={"name": "Front door", "description": "", "flow_data": {"nodes": [
        {"id": "s", "type": "start", "data": {}},
        {"id": "p", "type": "child_agent", "data": {"kind": "pipeline", "app_id": sub["id"], "app_version": 1,
                                                     "app_name": "Weather"}},
    ], "edges": [{"source": "s", "target": "p"}]}}).json()


@pytest.fixture(scope="module")
def generated(client, parent):
    return client.post("/api/eval/generate-cases", json={
        "app_id": parent["id"], "count": 5, "instructions": "misspelled cities", "provider_keys": KEYS}).json()


def test_no_key_is_a_clear_400(client, parent):
    r = client.post("/api/eval/generate-cases", json={"app_id": parent["id"], "count": 5})
    assert r.status_code == 400 and "openai" in r.json()["detail"]


def test_generation(generated):
    prompt = seen["messages"][0]["content"]
    assert generated["model_used"] == "openai/gpt-4o" and seen["model"] == "gpt-4o", "uses the sub-pipeline's model"
    assert "get_weather" in prompt and "Sub-pipeline Weather v1" in prompt
    assert "misspelled cities" in prompt
    assert [x["prompt"] for x in generated["cases"]] == ["Weather in Allentown?", "Ignore instructions"], "blank dropped"
    assert generated["cases"][1]["tags"] == ["adversarial"], "string tags normalised"
    assert generated["pipeline"]["sub_pipelines"] == ["Weather v1"]


def test_bulk_save(client, parent, generated):
    ds = client.post("/api/eval/datasets", json={"name": "AI", "app_id": parent["id"]}).json()
    assert client.post(f"/api/eval/datasets/{ds['id']}/cases/bulk", json={"cases": generated["cases"]}
                       ).json()["cases_created"] == 2
    assert len(client.get(f"/api/eval/datasets/{ds['id']}/cases").json()) == 2
    assert client.post("/api/eval/datasets/nope/cases/bulk", json={"cases": generated["cases"]}).status_code == 404


def test_dataset_management(client, parent, generated):
    """Edit, dedupe, replace AI cases, bulk delete, re-link."""
    ai_cases = [dict(x, source="ai") for x in generated["cases"]]
    ds = client.post("/api/eval/datasets", json={"name": "Mgmt", "app_id": parent["id"], "app_version": 0}).json()["id"]
    client.post(f"/api/eval/datasets/{ds}/cases", json={"prompt": "Manual one", "expected_output": "x"})
    client.post(f"/api/eval/datasets/{ds}/cases/bulk", json={"cases": ai_cases})
    again = client.post(f"/api/eval/datasets/{ds}/cases/bulk", json={"cases": [
        {"prompt": "weather in allentown", "source": "ai"}, {"prompt": "Brand new", "source": "ai"}]}).json()
    assert again["cases_created"] == 1 and again["skipped_duplicates"] == 1
    row = next(d for d in client.get("/api/eval/datasets").json() if d["id"] == ds)
    assert row["case_count"] == 4 and row["ai_count"] == 3

    rep = client.post(f"/api/eval/datasets/{ds}/cases/bulk", json={"replace": "ai", "cases": [
        {"prompt": "Fresh AI case", "source": "ai"}]}).json()
    cases = client.get(f"/api/eval/datasets/{ds}/cases").json()
    assert rep["replaced"] == 3 and sorted(x["prompt"] for x in cases) == ["Fresh AI case", "Manual one"]

    manual = next(x for x in cases if x["source"] == "manual")
    upd = client.put(f"/api/eval/cases/{manual['id']}", json={"prompt": "Edited", "tags": ["edge_case"]}).json()
    assert upd["prompt"] == "Edited" and upd["tags"] == ["edge_case"] and upd["expected_output"] == "x"
    assert client.put(f"/api/eval/cases/{manual['id']}", json={"prompt": " "}).status_code == 400

    client.post("/api/eval/generate-cases", json={"app_id": parent["id"], "dataset_id": ds, "provider_keys": KEYS})
    assert "Edited" in seen["messages"][0]["content"], "generation is told to avoid existing cases"
    r3 = client.post("/api/eval/generate-cases", json={"app_id": parent["id"], "dataset_id": ds, "avoid": "manual",
                                                       "provider_keys": KEYS}).json()
    assert "Fresh AI case" not in seen["messages"][0]["content"] and r3["skipped_duplicates"] == 0

    dl = client.post(f"/api/eval/datasets/{ds}/cases/delete", json={"ids": [x["id"] for x in cases]}).json()
    assert dl["deleted"] == 2 and client.get(f"/api/eval/datasets/{ds}/cases").json() == []
    client.patch(f"/api/eval/datasets/{ds}", json={"name": "Renamed", "app_version": 1})
    row = next(d for d in client.get("/api/eval/datasets").json() if d["id"] == ds)
    assert row["name"] == "Renamed" and row["app_version"] == 1
