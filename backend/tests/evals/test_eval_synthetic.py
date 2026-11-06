"""Synthetic Data node: preview, full generation in batches (NDJSON), and saving rows into an
eval dataset. The model call is stubbed at the backend, so the gateway still runs."""
import json
import re

import pytest

import llm
from routers import eval as eval_router

LLM = {"provider": "openai", "model": "gpt-4o", "api_key": "sk-test"}
COLUMNS = [
    {"name": "question", "type": "string", "nullable": False, "unique": True},
    {"name": "answer", "type": "string", "nullable": False, "unique": False},
]
calls = []
script = {"mode": "ok"}


@pytest.fixture(scope="module", autouse=True)
def _stub_openai(env):
    async def fake_complete(req):
        prompt = req.messages[0]["content"]
        calls.append(prompt)
        n = int(re.search(r"Rows to return now: (\d+)", prompt).group(1))
        batch = re.search(r"This is batch (\d+)", prompt)
        b = int(batch.group(1)) if batch else 0
        mode = script["mode"]
        if mode == "prose":
            return llm.LLMResponse(text="Sorry, I can't do that.")
        if mode == "fail_first" and b == 1:
            raise llm.LLMError("rate limited", provider="openai", status=429)
        rows = [{"question": f"q{b}-{i}", "answer": f"a{b}-{i}"} for i in range(n)]
        if mode == "dupes" and b == 1:
            rows[1]["question"] = rows[0]["question"]      # one duplicate in a unique column
            rows[2]["answer"] = None                       # one row missing a required column
        return llm.LLMResponse(text="```json\n" + json.dumps(rows) + "\n```")

    env.setattr(llm.backend_for("openai"), "complete", fake_complete)


@pytest.fixture(autouse=True)
def _reset():
    calls.clear()
    script["mode"] = "ok"


def spec(**fields):
    return {"llm_config": LLM, "dataset_name": "faq", "row_count": 10, "columns": COLUMNS, **fields}


def generate(client, **fields):
    r = client.post("/api/eval/synthetic-generate", json=spec(**fields))
    assert r.status_code == 200, r.text
    lines = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    return lines[:-1], lines[-1]


def test_preview(client):
    r = client.post("/api/eval/synthetic-preview", json=spec(preview_rows=3))
    assert r.status_code == 200
    assert r.json()["rows"] == [{"question": f"q0-{i}", "answer": f"a0-{i}"} for i in range(3)]
    assert "question: string (unique, required)" in calls[0]


def test_preview_bad_json_is_502(client):
    script["mode"] = "prose"
    r = client.post("/api/eval/synthetic-preview", json=spec())
    assert r.status_code == 502 and "JSON array" in r.json()["detail"]


def test_missing_key_is_400(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = client.post("/api/eval/synthetic-generate", json=spec(llm_config={**LLM, "api_key": ""}))
    assert r.status_code == 400 and "No API key" in r.json()["detail"]


def test_full_generation_in_batches(client):
    progress, done = generate(client, row_count=60)
    assert done["type"] == "done" and done["generated"] == 60 and len(done["rows"]) == 60
    assert len(calls) == 3, "60 rows = batches of 25 + 25 + 10"
    assert sorted(re.search(r"Rows to return now: (\d+)", c).group(1) for c in calls) == ["10", "25", "25"]
    assert len({r["question"] for r in done["rows"]}) == 60, "batches don't repeat each other"
    assert [p["type"] for p in progress] == ["progress"] * 3 and progress[-1]["rows"] == 60


def test_invalid_and_duplicate_rows_are_replaced(client):
    script["mode"] = "dupes"
    _, done = generate(client, row_count=25)
    assert done["generated"] == 25 and done["dropped_rows"] == 2
    assert len(calls) == 2, "an extra round makes up the dropped rows"
    assert all(r["answer"] for r in done["rows"])
    assert len({r["question"] for r in done["rows"]}) == 25


def test_a_failed_batch_is_skipped_and_reported(client):
    script["mode"] = "fail_first"
    _, done = generate(client, row_count=50)
    assert done["type"] == "done" and done["failed_batches"] >= 1 and "rate limited" in done["warning"]
    assert done["generated"] == 50, "later rounds fill in for the failed batch"


def test_all_batches_failing_is_an_error_line(client):
    script["mode"] = "prose"
    _, last = generate(client, row_count=5)
    assert last["type"] == "error" and "JSON array" in last["detail"]


def test_row_limit(client):
    r = client.post("/api/eval/synthetic-generate", json=spec(row_count=eval_router.SYNTHETIC_MAX_ROWS + 1))
    assert r.status_code == 400 and "limited" in r.json()["detail"]


def test_mock_provider_is_typed_and_seeded(client):
    cols = [{"name": "id", "type": "uuid", "unique": True}, {"name": "age", "type": "integer", "min": 18, "max": 30},
            {"name": "tier", "type": "category", "values": "gold, silver"}, {"name": "ok", "type": "boolean"}]
    body = {"llm_config": {"provider": "mock", "model": "mock-gpt-4"}, "row_count": 40, "columns": cols, "seed": 7}
    first = client.post("/api/eval/synthetic-generate", json=body).text.splitlines()[-1]
    again = client.post("/api/eval/synthetic-generate", json=body).text.splitlines()[-1]
    rows = json.loads(first)["rows"]
    assert first == again, "same seed, same rows"
    assert len(rows) == 40 and len({r["id"] for r in rows}) == 40
    assert all(18 <= r["age"] <= 30 and r["tier"] in ("gold", "silver") and isinstance(r["ok"], bool) for r in rows)
    assert not calls


def test_save_into_new_and_existing_dataset(client):
    rows = [{"question": "What is 2+2?", "answer": "4"}, {"question": "Capital of France?", "answer": "Paris"},
            {"question": "", "answer": "skipped: empty prompt"}]
    r = client.post("/api/eval/synthetic-save", json={
        "rows": rows, "dataset_name": "Synthetic FAQ", "prompt_column": "question", "expected_column": "answer"})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["cases_created"] == 2 and saved["rows"] == 3
    cases = client.get(f"/api/eval/datasets/{saved['dataset_id']}/cases").json()
    assert {(c["prompt"], c["expected_output"]) for c in cases} == {("What is 2+2?", "4"), ("Capital of France?", "Paris")}
    assert all(c["source"] == "ai" and c["tags"] == ["synthetic"] for c in cases)
    ds = next(d for d in client.get("/api/eval/datasets").json() if d["id"] == saved["dataset_id"])
    assert ds["name"] == "Synthetic FAQ" and ds["ai_count"] == 2

    again = client.post("/api/eval/synthetic-save", json={
        "rows": rows[:1] + [{"question": "Largest planet?", "answer": "Jupiter"}], "dataset_id": saved["dataset_id"],
        "prompt_column": "question", "expected_column": "answer"}).json()
    assert again["cases_created"] == 1 and again["skipped_duplicates"] == 1


def test_save_whole_row_as_prompt(client):
    r = client.post("/api/eval/synthetic-save", json={"rows": [{"name": "Ana", "age": 31, "label": "adult"}],
                                                      "expected_column": "label"}).json()
    case = client.get(f"/api/eval/datasets/{r['dataset_id']}/cases").json()[0]
    assert json.loads(case["prompt"]) == {"name": "Ana", "age": 31} and case["expected_output"] == "adult"


def test_save_rejects_unknown_prompt_column(client):
    r = client.post("/api/eval/synthetic-save", json={"rows": [{"a": 1}], "prompt_column": "question"})
    assert r.status_code == 400
    r = client.post("/api/eval/synthetic-save", json={"rows": [{"a": 1}], "dataset_id": "nope", "prompt_column": "a"})
    assert r.status_code == 404
