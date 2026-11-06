"""AI starter-prompt suggestions for the Run panel (stubbed model call)."""
import json

import pytest

import llm

seen = {}
FLOW = {"nodes": [
    {"id": "l", "type": "llm", "data": {"provider": "openai", "model": "gpt-4o",
                                        "system_prompt": "You answer HR policy questions."}},
    {"id": "r", "type": "retriever", "data": {"collection_name": "hr_handbook"}},
], "edges": []}


@pytest.fixture(scope="module", autouse=True)
def _stub_openai(env):
    async def fake_complete(req):
        seen.update(vars(req))
        prompts = ["How many vacation days do new hires get?", "What is the parental leave policy?",
                   "Can I carry over unused PTO?", "extra"]
        return llm.LLMResponse(text="```json\n" + json.dumps(prompts) + "\n```")

    # Stub the backend, not llm.complete, so the gateway (key resolution) still runs
    env.setattr(llm.backend_for("openai"), "complete", fake_complete)


def test_suggestions(client):
    r = client.post("/api/eval/suggest-prompts", json={"flow_data": FLOW, "app_name": "HR Bot",
                                                       "provider_keys": {"openai": "sk-test"}})
    assert r.status_code == 200
    assert r.json()["prompts"] == ["How many vacation days do new hires get?", "What is the parental leave policy?",
                                   "Can I carry over unused PTO?"], "trimmed to count"
    meta = seen["messages"][0]["content"]
    assert "HR policy" in meta and "hr_handbook" in meta and "HR Bot" in meta, "meta-prompt describes the canvas"


def test_refusals(client):
    assert client.post("/api/eval/suggest-prompts", json={"flow_data": FLOW}).status_code == 400, "no key"
    mock = {"nodes": [{"id": "l", "type": "llm", "data": {"provider": "mock", "model": "m"}}], "edges": []}
    assert client.post("/api/eval/suggest-prompts", json={"flow_data": mock}).status_code == 400, "mock model"
