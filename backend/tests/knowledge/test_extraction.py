"""Structured extraction with field-level citations and the review queue (plan.md P1): field parsing,
quote checks against the cited page, the Structured Extract tool end to end (model stubbed), and
/api/reviews decisions, audit trail and export to an eval dataset. Steps of one scenario, in order."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from db import get_db_connection
from helpers import hdr
from services import extraction, extraction_reviews

ADMIN = hdr()
PAGES = [
    {"text": "LEASE AGREEMENT between Maple Grove Owner LLC (Landlord) and Sunrise Care LLC (Tenant).",
     "metadata": {"source": "lease.pdf", "page": 1}},
    {"text": "4.1 Term. The term commences on January 1, 2020 and expires on December 31, 2034.\n"
             "4.2 Base Rent. Tenant shall pay monthly base rent of $185,000.00.",
     "metadata": {"source": "lease.pdf", "page": 2}},
    {"text": "9.3 Licensure. Tenant shall maintain at all times a valid skilled nursing facility license.",
     "metadata": {"source": "lease.pdf", "page": 3}},
]
FIELDS = "lease_end: Lease expiration date\nMonthly Base Rent: rent per month\ntenant_entity\nguarantor: who guarantees it"
ANSWER = {"fields": [
    {"name": "lease_end", "value": "2034-12-31", "page": 2,
     "quote": "expires on December 31, 2034", "confidence": 0.95},
    {"name": "monthly_base_rent", "value": 185000, "page": 1,           # wrong page, right quote
     "quote": "monthly base rent of $185,000.00", "confidence": 0.9},
    {"name": "tenant_entity", "value": "Sunrise Senior Care Inc", "page": 1,   # quote not in the document
     "quote": "Sunrise Senior Care Inc (Tenant)", "confidence": 0.8},
    {"name": "guarantor", "value": None, "page": None, "quote": None, "confidence": 0.9},
]}
state = {}


def test_parse_fields():
    fields = extraction.parse_fields(FIELDS)
    assert [f["name"] for f in fields] == ["lease_end", "monthly_base_rent", "tenant_entity", "guarantor"]
    assert fields[0]["description"] == "Lease expiration date" and fields[2]["description"] == ""
    assert [f["name"] for f in extraction.parse_fields('[{"name": "Rent", "type": "money"}, "rent", "beds"]')] \
        == ["rent", "beds"], "JSON form; duplicates dropped"
    assert extraction.parse_fields('[{"name": "rent", "type": "money"}]')[0]["type"] == "money"
    with pytest.raises(extraction.ExtractionError, match="No fields"):
        extraction.parse_fields("  \n# just a comment")
    with pytest.raises(extraction.ExtractionError, match="valid JSON"):
        extraction.parse_fields("[oops")


def test_quote_checks():
    page = "4.2 Base Rent.  Tenant shall pay monthly\nbase rent of $185,000.00."
    assert extraction.quote_found("monthly base rent of $185,000.00", page), "whitespace and punctuation aside"
    assert extraction.quote_found("monthly base rent of $185,00O.00", page), "OCR-like noise within 90%"
    assert not extraction.quote_found("monthly base rent of $95,000.00 payable quarterly in arrears", page)
    assert not extraction.quote_found("", page)

    pages = extraction.pages_of([dict(d) for d in PAGES])
    results = {r["name"]: r for r in extraction.check(ANSWER["fields"], extraction.parse_fields(FIELDS), pages)}
    assert results["lease_end"]["verified"] and results["lease_end"]["confidence"] == 0.95
    assert results["monthly_base_rent"]["verified"] and results["monthly_base_rent"]["page"] == 2, \
        "a quote found on another page moves the citation there"
    assert not results["tenant_entity"]["verified"] and results["tenant_entity"]["confidence"] == 0.3
    assert results["guarantor"]["value"] is None and results["guarantor"]["confidence"] == 0.0


def test_pages_numbered_in_order_when_they_repeat():
    docs = [{"text": "Email body", "metadata": {"source": "m.eml"}},
            {"text": "License p1", "metadata": {"source": "m.eml", "attachment": "license.pdf", "page": 1}},
            {"text": "Roster", "metadata": {"source": "m.eml", "attachment": "roster.xlsx", "sheet": "Q3"}}]
    pages = extraction.pages_of(docs)
    assert [(p["page"], p["label"]) for p in pages] == [(1, None), (2, "license.pdf p.1"), (3, "roster.xlsx sheet Q3")]
    msgs = extraction.build_messages(pages, extraction.parse_fields("x"))
    assert '<page number="2" from="license.pdf p.1">' in msgs[1]["content"]
    with pytest.raises(extraction.ExtractionError, match="limit is 10"):
        extraction.build_messages(pages, extraction.parse_fields("x"), max_chars=10)


def test_tool_extracts_and_queues_for_review(tmp_path, monkeypatch):
    import llm
    import loaders
    from services.secret_store import request_scope
    from tools.data import structured_extract

    seen = {}

    async def fake_load(loader_type, source, cfg):
        seen["loader"] = loader_type
        seen["ocr"] = (cfg["ocr_engine"], cfg["ocr_provider"], cfg["ocr_model"])
        return [dict(d) for d in PAGES]

    async def fake_complete(req):
        seen["model"] = (req.provider, req.model, req.temperature)
        seen["prompt"] = req.messages[1]["content"]
        return SimpleNamespace(text="Here you go:\n" + json.dumps(ANSWER))

    monkeypatch.setattr(loaders, "load_documents", fake_load)
    monkeypatch.setattr(llm, "complete", fake_complete)
    cfg = {**structured_extract.TOOL.default_config, "fields": FIELDS, "loader": "docling", "batch": "maple-grove"}
    token = request_scope.set(("tenant_demo", "proj_research"))
    try:
        out = json.loads(asyncio.run(structured_extract.run("/data/leases/lease.pdf", cfg, "structured_extract")))
    finally:
        request_scope.reset(token)
    assert seen["loader"] == "docling" and seen["model"] == ("openai", "gpt-4o-mini", 0.0)
    assert seen["ocr"] == ("auto", "openai", "gpt-4o-mini"), "vision OCR defaults to the node's model"
    assert '<page number="2">' in seen["prompt"] and "- guarantor (text): who guarantees it" in seen["prompt"]
    assert out["unverified"] == ["tenant_entity"] and out["not_found"] == ["guarantor"]
    assert out["review"] == {"queued": 4, "where": "Evaluate → Review queue"}

    no_review = {**cfg, "review": "off"}
    out = json.loads(asyncio.run(structured_extract.run("/data/leases/lease.pdf", no_review, "x")))
    assert "review" not in out
    assert "No fields" in asyncio.run(structured_extract.run("/x.pdf", {**cfg, "fields": ""}, "x"))
    assert "Give the path" in asyncio.run(structured_extract.run("  ", cfg, "x"))


def test_review_queue_lists_weakest_fields_first(client):
    r = client.get("/api/reviews", params={"batch": "maple-grove"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"] == {"pending": 4, "approved": 0, "corrected": 0, "rejected": 0}
    items = body["items"]
    assert [i["field"] for i in items[:2]] == ["guarantor", "tenant_entity"], "unverified, lowest confidence first"
    by_field = {i["field"]: i for i in items}
    assert by_field["monthly_base_rent"]["value"] == 185000, "values keep their JSON type"
    assert by_field["lease_end"]["quote"] == "expires on December 31, 2034" and by_field["lease_end"]["page"] == 2
    assert by_field["lease_end"]["model"] == "openai/gpt-4o-mini"
    state.update({f: i["id"] for f, i in by_field.items()})
    other = client.get("/api/reviews", headers=hdr(project="proj_other"))
    assert other.status_code in (200, 403) and (other.status_code == 403 or not other.json()["items"]), \
        "other projects don't see the queue"


def test_decisions(client):
    def decide(field, **body):
        return client.post(f"/api/reviews/{state[field]}/decision", json=body, headers=ADMIN)

    r = decide("lease_end", decision="approve")
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["final_value"] == "2034-12-31"
    assert r.json()["reviewed_by"] == "user_admin" and r.json()["reviewed_at"]
    assert decide("tenant_entity", decision="correct").status_code == 400, "a correction needs the value"
    r = decide("tenant_entity", decision="correct", value="Sunrise Care LLC", note="name on page 1")
    assert r.json()["status"] == "corrected" and r.json()["final_value"] == "Sunrise Care LLC"
    assert decide("guarantor", decision="reject").json()["final_value"] is None
    assert decide("lease_end", decision="maybe").status_code == 400
    assert client.post("/api/reviews/rv_nope/decision", json={"decision": "approve"}, headers=ADMIN).status_code == 404
    counts = client.get("/api/reviews", params={"batch": "maple-grove"}, headers=ADMIN).json()["counts"]
    assert counts == {"pending": 1, "approved": 1, "corrected": 1, "rejected": 1}
    pending = client.get("/api/reviews", params={"status": "pending"}, headers=ADMIN).json()["items"]
    assert [i["field"] for i in pending] == ["monthly_base_rent"]


def test_export_waits_for_complete_documents(client):
    r = client.post("/api/reviews/export", json={"dataset_name": "Lease abstraction"}, headers=ADMIN)
    assert r.status_code == 409, "the lease still has a pending field"
    client.post(f"/api/reviews/{state['monthly_base_rent']}/decision", json={"decision": "approve"}, headers=ADMIN)
    assert client.post("/api/reviews/export", json={}, headers=ADMIN).status_code == 400
    r = client.post("/api/reviews/export", json={"dataset_name": "Lease abstraction"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["cases_created"] == 1 and r.json()["documents"] == 1
    cases = client.get(f"/api/eval/datasets/{r.json()['dataset_id']}/cases", headers=ADMIN).json()
    assert len(cases) == 1 and cases[0]["prompt"] == "/data/leases/lease.pdf"
    assert json.loads(cases[0]["expected_output"]) == {
        "guarantor": None, "lease_end": "2034-12-31", "monthly_base_rent": 185000, "tenant_entity": "Sunrise Care LLC"}
    assert cases[0]["tags"] == ["extraction-review", "corrected"]
    again = client.post("/api/reviews/export", json={"dataset_id": r.json()["dataset_id"]}, headers=ADMIN).json()
    assert again["cases_created"] == 0 and again["skipped_duplicates"] == 1


def test_refiling_replaces_only_pending_rows():
    ids = extraction_reviews.add("tenant_demo", "proj_research", "/data/leases/lease.pdf",
                                 [{"name": "lease_end", "value": "2035-01-01"}], batch="maple-grove")
    rows = extraction_reviews.list_reviews("tenant_demo", "proj_research", batch="maple-grove")
    assert rows["counts"]["pending"] == 1 and rows["counts"]["approved"] == 2, "decided rows are kept"
    assert extraction_reviews.add("tenant_demo", "proj_research", "/data/leases/lease.pdf", [], batch="maple-grove") == []
    assert extraction_reviews.get("tenant_demo", "proj_research", ids[0]) is None


def test_decisions_are_audited():
    conn = get_db_connection()
    try:
        actions = [r[0] for r in conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'review.%' ORDER BY created_at")]
    finally:
        conn.close()
    assert actions.count("review.decide") >= 4 and "review.export" in actions
