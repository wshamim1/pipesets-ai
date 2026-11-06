"""Batch runs over documents (plan.md F5 → P1): uploaded files become one row each, ``{document}`` is the
file's text read when its row runs, unreadable files fail without a run, a Structured Extract pipeline
files its fields in the review queue under the batch's name, and deleting the batch removes the files.
The tests are steps of one scenario, in order."""
import json
import os
from types import SimpleNamespace

import pytest

from db import get_db_connection
from helpers import hdr, mock_flow, run_jobs
from services import batches

ADMIN = hdr()
state = {}


def items(client, batch_id):
    return client.get(f"/api/batches/{batch_id}/items", headers=ADMIN).json()["items"]


def goal(run_id):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT goal FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    return row["goal"] if row else None


def upload(client, app_id, files, **form):
    return client.post("/api/batches/documents", headers=ADMIN,
                       files=[("files", (name, data)) for name, data in files],
                       data={"app_id": app_id, **{k: str(v) for k, v in form.items()}})


@pytest.fixture(scope="module")
def app_id(client):
    aid = client.post("/api/apps", json={"name": "Summariser", "flow_data": mock_flow("sum")}, headers=ADMIN).json()["id"]
    assert client.post(f"/api/apps/{aid}/publish", headers=ADMIN).status_code == 200
    return aid


def test_each_document_is_a_row_with_its_text(client, app_id):
    files = [("lease-a.txt", b"Monthly rent is $1,200. Term ends 2031."),
             ("lease-b.md", b"# Lease B\nRent: $900 per month."),
             ("broken.pdf", b"this is not a pdf")]
    r = upload(client, app_id, files, prompt_template="Summarise {filename}:\n{document}", name="Q3 leases", concurrency=2)
    assert r.status_code == 201, r.text
    batch = r.json()
    state["batch"] = batch["id"]
    assert batch["total"] == 3 and batch["source"]["kind"] == "documents" and batch["columns"] == ["filename", "path"]
    stored = items(client, batch["id"])
    assert stored[0]["prompt"] == "Summarise lease-a.txt:\n‹text of lease-a.txt›", "the text isn't copied into the row"
    assert os.path.isfile(stored[0]["input"]["path"])
    assert stored[0]["input"]["path"].startswith(batches.documents_dir(batch["id"]))

    run_jobs()
    done = items(client, batch["id"])
    assert [i["status"] for i in done] == ["completed", "completed", "failed"]
    assert goal(done[0]["run_id"]) == "Summarise lease-a.txt:\nMonthly rent is $1,200. Term ends 2031."
    assert "Rent: $900 per month." in goal(done[1]["run_id"])
    assert done[2]["error"].startswith("Couldn't read broken.pdf") and done[2]["run_id"] is None, "no run was paid for"
    assert client.get(f"/api/batches/{batch['id']}", headers=ADMIN).json()["status"] == "done"


def test_uploads_are_checked(client, app_id):
    assert upload(client, app_id, [("x.exe", b"MZ")]).status_code == 415
    r = upload(client, app_id, [("a.txt", b"hi")], prompt_template="{document} {tenant}")
    assert r.status_code == 422 and "tenant" in r.json()["detail"] and "document" in r.json()["detail"]
    assert upload(client, app_id, [("a.txt", b"hi")], loader="magic").status_code == 422
    # Nothing is left on disk for a batch that wasn't created
    root = os.path.dirname(batches.documents_dir("x"))
    assert sorted(os.listdir(root)) == [state["batch"]]


def test_long_documents_are_cut(tmp_path):
    import asyncio
    path = tmp_path / "long.txt"
    path.write_text("word " * 1000)
    text = asyncio.run(batches.read_document({"max_chars": 1000}, str(path)))
    assert len(text) < 1100 and text.endswith("[… cut at 1000 characters]")


def test_structured_extract_files_fields_under_the_batch_name(client, monkeypatch):
    import llm

    async def fake_complete(req):
        return SimpleNamespace(text=json.dumps({"fields": [
            {"name": "monthly_rent", "value": 1200, "page": 1, "quote": "Monthly rent is $1,200", "confidence": 0.9}]}))

    monkeypatch.setattr(llm, "complete", fake_complete)
    flow = {"nodes": [
        {"id": "llm", "type": "llm", "data": {"label": "LLM", "provider": "mock", "model": "mock-gpt-4"}},
        {"id": "x", "type": "tool", "data": {"label": "Structured Extract", "toolId": "structured_extract", "config": {
            "loader": "text", "fields": "monthly_rent: rent per month", "provider": "openai", "model": "gpt-4o-mini",
            "review": "queue", "batch": ""}}},
    ], "edges": [{"source": "llm", "target": "x"}]}
    app_id = client.post("/api/apps", json={"name": "Lease abstraction", "flow_data": flow}, headers=ADMIN).json()["id"]
    assert client.post(f"/api/apps/{app_id}/publish", headers=ADMIN).status_code == 200

    r = upload(client, app_id, [("maple.txt", b"Monthly rent is $1,200. Term ends 2031.")],
               prompt_template="{path}", name="Maple Grove leases")
    assert r.status_code == 201, r.text
    run_jobs()
    assert [i["status"] for i in items(client, r.json()["id"])] == ["completed"]
    reviews = client.get("/api/reviews", params={"batch": "Maple Grove leases"}, headers=ADMIN).json()["items"]
    assert [(i["field"], i["value"], i["verified"]) for i in reviews] == [("monthly_rent", 1200, True)]
    assert reviews[0]["source"].endswith("maple.txt")


def test_deleting_the_batch_removes_its_documents(client):
    folder = batches.documents_dir(state["batch"])
    assert os.path.isdir(folder)
    assert client.delete(f"/api/batches/{state['batch']}", headers=ADMIN).status_code == 200
    assert not os.path.exists(folder)
